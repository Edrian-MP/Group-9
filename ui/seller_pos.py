import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk
import cv2
import numpy as np
import datetime
import sys
import os
import logging
import json
import time
from collections import deque, Counter
import threading

# Ensure project root is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import config
from ui.price_inquiry import PriceInquiryWindow 

logger = logging.getLogger(__name__)

class SellerPOS:
    def __init__(self, root, db, camera, scale, printer, logout_cb, current_user=None, ai_engine=None):
        self.root = root
        self.db = db
        self.camera = camera
        self.scale = scale
        self.printer = printer
        self.logout_cb = logout_cb
        user = current_user or {}
        self.current_user = {
            "pin": str(user.get("pin") or ""),
            "name": str(user.get("name") or "Unknown"),
            "role": str(user.get("role") or "Unknown")
        }
        
        self.cart = []
        self.current_product = None
        self.current_price = 0.0    # cached price for current_product
        self.running = True
        self.price_check_win = None
        self._ai_frame_counter = 0        # throttle: run AI every N UI loops
        self._ai_inference_interval = int(getattr(config, "AI_INFERENCE_INTERVAL", 2))
        self._prediction_history = deque(maxlen=7)  # rolling vote window
        self._fast_lock_min_confidence = float(getattr(config, "AI_FAST_LOCK_MIN_CONFIDENCE", 0.92))
        self._fast_lock_min_cameras = 2
        self._switch_label_min_confidence = float(getattr(config, "AI_SWITCH_LABEL_MIN_CONFIDENCE", 0.96))
        self._switch_label_min_votes = int(getattr(config, "AI_SWITCH_LABEL_MIN_VOTES", 3))
        self._switch_required_consecutive = int(getattr(config, "AI_SWITCH_REQUIRED_CONSECUTIVE", 2))
        self._min_lock_hold_seconds = float(getattr(config, "AI_MIN_LOCK_HOLD_SECONDS", 0.70))
        self._product_lock_timestamp = 0.0
        self._switch_candidate_label = None
        self._switch_candidate_count = 0
        self._weight_change_threshold_kg = float(getattr(config, "AI_WEIGHT_CHANGE_THRESHOLD_KG", 0.03))
        self._weight_transition_window_s = float(getattr(config, "AI_WEIGHT_TRANSITION_WINDOW_S", 1.20))
        self._weight_empty_threshold_kg = float(getattr(config, "AI_WEIGHT_EMPTY_THRESHOLD_KG", 0.008))
        self._last_weight_kg = 0.0
        self._last_weight_transition_ts = 0.0
        self._pending_manual_training_frames = {}
        self._max_manual_training_frames_per_product = 12
        configured_profile = str(getattr(config, "AI_RECOGNITION_PROFILE", "strict") or "strict").strip().lower()
        self._ai_profile_name = configured_profile if configured_profile in {"strict", "balanced"} else "strict"
        self._ai_profile_presets = {
            "strict": {
                "ai_inference_interval": 2,
                "fast_lock_min_confidence": 0.92,
                "switch_label_min_confidence": 0.96,
                "switch_label_min_votes": 3,
                "switch_required_consecutive": 2,
                "min_lock_hold_seconds": 0.70,
                "weight_change_threshold_kg": 0.03,
                "weight_transition_window_s": 1.20,
                "weight_empty_threshold_kg": 0.008,
            },
            "balanced": {
                "ai_inference_interval": 2,
                "fast_lock_min_confidence": 0.90,
                "switch_label_min_confidence": 0.94,
                "switch_label_min_votes": 2,
                "switch_required_consecutive": 1,
                "min_lock_hold_seconds": 0.45,
                "weight_change_threshold_kg": 0.025,
                "weight_transition_window_s": 1.00,
                "weight_empty_threshold_kg": 0.008,
            },
        }
        self._mode = "AUTO"               # "AUTO" or "MANUAL"
        self._is_predicting = False       # Prevents AI traffic jams
        self._latest_ai_result = {
            'fused_label': None,
            'fused_confidence': 0.0,
            'per_frame_predictions': [],
            'vote_counts': {},
            'active_frame_count': 0,
            'object_detections': [],
            'per_frame_detections': []
        }
        self._last_camera_count = 0
        self._last_ai_frame_shapes = []
        self._auto_status_text = ""
        self._auto_status_color = "#27ae60"
        self._ai_metrics_path = os.path.join(config.BASE_DIR, "data", "ai_metrics.jsonl")
        self._ai_metrics_lock = threading.Lock()
        
        # Reuse app-level AI engine to avoid repeated model loads.
        self.ai = ai_engine
        if self.ai is None:
            raise ValueError("SellerPOS requires a shared ai_engine instance.")
        
        self.setup_ui()
        self._initialize_ai_status()
        self.update_loop()

    def _get_ai_runtime_status(self):
        if hasattr(self.ai, "get_runtime_status") and callable(self.ai.get_runtime_status):
            try:
                return self.ai.get_runtime_status() or {}
            except Exception as e:
                logger.warning("AI status read failed: %s", e)
        return {}

    def _initialize_ai_status(self):
        status = self._get_ai_runtime_status()
        if not status:
            return

        if not bool(status.get("feature_extractor_ready", True)):
            self._set_auto_status("AI unavailable", "#c0392b")
            return

        if int(status.get("profiles_loaded") or 0) <= 0:
            self._set_auto_status("No AI profiles", "#e67e22")
            return

        self._set_auto_status("Ready", "#27ae60")

    def _get_ai_frames(self):
        if hasattr(self.camera, "get_all_raw_frames") and callable(self.camera.get_all_raw_frames):
            raw_frames = self.camera.get_all_raw_frames()
        else:
            raw_frames = [self.camera.get_raw_frame(i) for i in range(3)]
        return [raw_frame for raw_frame in raw_frames if raw_frame is not None]

    def logout(self):
        if self.price_check_win is not None and self.price_check_win.winfo_exists():
            try:
                self.price_check_win.close()
            except Exception:
                pass
        self._on_price_inquiry_close()
        self.running = False
        self.logout_cb()

    def setup_ui(self):
        top_bar = ttk.Frame(self.root, style="Brand.TFrame", padding="20 10")
        top_bar.pack(fill=tk.X)
        
        ttk.Label(top_bar, text="SMART POS", style="Brand.TLabel").pack(side=tk.LEFT)
        
        ttk.Button(top_bar, text="LOGOUT", command=self.logout, style="Danger.TButton").pack(side=tk.RIGHT, padx=5)
        ttk.Button(top_bar, text="PRICE CHECK", style="Secondary.TButton", command=self.open_price_check).pack(side=tk.RIGHT, padx=5)
        self.btn_mode = tk.Button(top_bar, text="⚡ AUTO MODE", font=("Segoe UI", 11, "bold"),
                                  bg="#27ae60", fg="white", relief="flat", padx=12, pady=6,
                                  command=self.toggle_mode)
        self.btn_mode.pack(side=tk.RIGHT, padx=10)

        content = ttk.Frame(self.root, style="Main.TFrame", padding=15)
        content.pack(fill=tk.BOTH, expand=True)

        # LEFT: Camera & Scale Display
        left_panel = ttk.Frame(content, style="Main.TFrame")
        left_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        
        cam_card = ttk.Frame(left_panel, style="Card.TFrame", padding=5)
        cam_card.pack(fill=tk.BOTH, expand=True, pady=(0, 15))
        
        self.cam_container = tk.Frame(cam_card, bg="white", width=400, height=300)
        self.cam_container.pack(fill=tk.BOTH, expand=True)
        self.cam_container.pack_propagate(False) 
        self.cam_label = tk.Label(self.cam_container, bg="white", text="Camera Feed", fg="#95a5a6", font=("Segoe UI", 12))
        self.cam_label.pack(fill=tk.BOTH, expand=True)
        
        scale_card = ttk.Frame(left_panel, style="Card.TFrame", padding=15)
        scale_card.pack(fill=tk.X)
        
        ttk.Label(scale_card, text="WEIGHT READING", style="Card.TLabel", foreground="#7f8c8d").pack(anchor="w")
        self.lbl_weight = tk.Label(scale_card, text="0.00 kg", font=("Segoe UI", 48, "bold"), fg="#f1c40f", bg="white")
        self.lbl_weight.pack(pady=5)

        tare_btn = ttk.Button(scale_card, text="TARE / ZERO SCALE", style="Secondary.TButton", command=self.tare_scale)
        tare_btn.pack(pady=(4, 0))
        self._remove_legacy_scale_controls(scale_card)

        # CENTER: Manual Product Quick Select
        center_panel = ttk.Frame(content, style="Card.TFrame", padding=15)
        center_panel.pack(side=tk.LEFT, fill=tk.BOTH, padx=10, expand=True)
        
        ttk.Label(center_panel, text="Quick Select", style="SubHeader.TLabel", background="white").pack(anchor="w", pady=(0, 10))
        
        canvas_frame = tk.Frame(center_panel, bg="white")
        canvas_frame.pack(fill=tk.BOTH, expand=True)
        
        canvas = tk.Canvas(canvas_frame, bg="white", highlightthickness=0)
        scroll_frame = tk.Frame(canvas, bg="white")
        
        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        
        canvas.pack(fill="both", expand=True)
        
        products = self.db.get_all_products()
        r, c = 0, 0
        for prod in products:
            name, price, stock = prod
            btn = tk.Button(scroll_frame, text=f"{name}\n₱{price}/kg", font=("Segoe UI", 11, "bold"), 
                            width=15, height=5, bg="#ecf0f1", fg="#2c3e50", relief="flat",
                            activebackground="#bdc3c7",
                            command=lambda n=name: self.select_product(n))
            btn.grid(row=r, column=c, padx=8, pady=8)
            c += 1
            if c > 1: 
                c = 0
                r += 1

        # RIGHT: AI Feedback & Shopping Cart
        right_panel = ttk.Frame(content, style="Card.TFrame", padding=15, width=360)
        right_panel.pack(side=tk.RIGHT, fill=tk.Y, padx=(10, 0))
        right_panel.pack_propagate(False)
        
        self.sel_frame = tk.Frame(right_panel, bg="#f8f9fa", pady=10, padx=10, height=120)
        self.sel_frame.pack(fill=tk.X, pady=(0, 10))
        self.sel_frame.pack_propagate(False)
        self.lbl_sel_header = tk.Label(
            self.sel_frame, text="⚡ AUTO — SELECTED ITEM",
            font=("Segoe UI", 10, "bold"), bg="#f8f9fa", fg="#27ae60"
        )
        self.lbl_sel_header.pack(anchor="w", fill=tk.X)
        self.lbl_sel_status = tk.Label(
            self.sel_frame, text="Ready",
            font=("Segoe UI", 9), bg="#f8f9fa", fg="#27ae60",
            anchor="w", justify="left", wraplength=310, height=2
        )
        self.lbl_sel_status.pack(anchor="w", fill=tk.X)
        self.lbl_selected = tk.Label(
            self.sel_frame, text="None",
            font=("Segoe UI", 18, "bold"), fg=config.ACCENT_COLOR, bg="#f8f9fa",
            anchor="center", justify="center", wraplength=300, height=2
        )
        self.lbl_selected.pack(fill=tk.X)

        cols = ("Item", "Kg", "Total")
        self.tree = ttk.Treeview(right_panel, columns=cols, show="headings", height=15)
        self.tree.column("Item", width=140, anchor="center")
        self.tree.column("Kg", width=70, anchor="center")
        self.tree.column("Total", width=90, anchor="center")
        
        for col in cols: 
            self.tree.heading(col, text=col, anchor="center")
        
        btn_frame = tk.Frame(right_panel, bg="white")
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X)
        
        ttk.Button(btn_frame, text="VOID SELECTED", style="Danger.TButton", command=self.void_item).pack(fill=tk.X, pady=5)
        ttk.Button(btn_frame, text="ADD TO CART", style="Primary.TButton", command=self.add_to_cart).pack(fill=tk.X, pady=5)
        ttk.Button(btn_frame, text="CHECKOUT / PRINT", style="Primary.TButton", command=self.checkout).pack(fill=tk.X, pady=(15, 0))

        self.lbl_total = tk.Label(right_panel, text="Total: ₱ 0.00", font=("Segoe UI", 24, "bold"), fg=config.ACCENT_COLOR, bg="white")
        self.lbl_total.pack(side=tk.BOTTOM, pady=15)
        
        self.tree.pack(side=tk.TOP, fill=tk.BOTH, expand=True, pady=10)

    def open_price_check(self):
        if self.price_check_win is not None and self.price_check_win.winfo_exists():
            self.price_check_win.lift()
            self._on_price_inquiry_open()
            return
        self.price_check_win = PriceInquiryWindow(
            self.root,
            self.db,
            self.scale,
            self.camera,
            selection_provider=self._get_price_inquiry_context,
            ai_engine=self.ai,
            state_callback=self._on_price_inquiry_state,
            on_open=self._on_price_inquiry_open,
            on_close=self._on_price_inquiry_close
        )

    def _on_price_inquiry_open(self):
        if hasattr(self.root, 'customer_display'):
            try:
                self.root.customer_display.show_price_inquiry_overlay()
            except Exception as e:
                logger.warning("Customer inquiry overlay open failed: %s", e)

    def _on_price_inquiry_close(self):
        if hasattr(self.root, 'customer_display'):
            try:
                self.root.customer_display.hide_price_inquiry_overlay()
            except Exception as e:
                logger.warning("Customer inquiry overlay close failed: %s", e)

    def _on_price_inquiry_state(self, state):
        if hasattr(self.root, 'customer_display'):
            try:
                self.root.customer_display.update_price_inquiry_overlay(state)
            except Exception as e:
                logger.warning("Customer inquiry overlay update failed: %s", e)

    def _get_price_inquiry_context(self):
        selected_product = self.current_product if self._mode == "MANUAL" else None
        selected_price = 0.0
        if selected_product:
            try:
                selected_price = float(self.current_price or self.db.get_product_price(selected_product))
            except Exception as e:
                logger.warning("Price inquiry manual lookup failed for %s: %s", selected_product, e)
        return {
            "mode": self._mode,
            "selected_product": selected_product,
            "selected_price": selected_price
        }

    def tare_scale(self):
        def _do_tare():
            try:
                self.scale.tare()
            except Exception as e:
                logger.warning("Tare failed: %s", e)
        threading.Thread(target=_do_tare, daemon=True).start()

    def _remove_legacy_scale_controls(self, parent):
        for widget in parent.winfo_children():
            if isinstance(widget, (tk.Scale, tk.Checkbutton)):
                widget.destroy()

    def smart_resize(self, image, target_w, target_h):
        h, w = image.shape[:2]
        scale = min(target_w/w, target_h/h)
        new_w, new_h = int(w * scale), int(h * scale)
        resized = cv2.resize(image, (new_w, new_h))
        canvas = np.zeros((target_h, target_w, 3), dtype=np.uint8)
        canvas[:] = (255, 255, 255)
        x_offset, y_offset = (target_w - new_w) // 2, (target_h - new_h) // 2
        try: canvas[y_offset:y_offset+new_h, x_offset:x_offset+new_w] = resized
        except: pass
        return canvas

    def _get_camera_tile_rects(self, frame_shape, camera_count):
        if not frame_shape or camera_count <= 0:
            return []

        h, w = frame_shape[:2]
        if camera_count == 1:
            return [(0, 0, w, h)]

        if camera_count == 2:
            mid_x = w // 2
            return [(0, 0, mid_x, h), (mid_x, 0, w, h)]

        if camera_count == 3:
            mid_x = w // 2
            mid_y = h // 2
            centered_x = (w - mid_x) // 2
            return [
                (0, 0, mid_x, mid_y),
                (mid_x, 0, w, mid_y),
                (centered_x, mid_y, centered_x + mid_x, h)
            ]

        mid_x = w // 2
        mid_y = h // 2
        return [
            (0, 0, mid_x, mid_y),
            (mid_x, 0, w, mid_y),
            (0, mid_y, mid_x, h),
            (mid_x, mid_y, w, h)
        ]

    def _project_detection_bbox(self, bbox, tile_rect, source_shape):
        if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
            return None

        tile_x1, tile_y1, tile_x2, tile_y2 = tile_rect
        tile_w = max(1, int(tile_x2 - tile_x1))
        tile_h = max(1, int(tile_y2 - tile_y1))

        src_h, src_w = 0, 0
        if isinstance(source_shape, (list, tuple)) and len(source_shape) >= 2:
            src_h = int(source_shape[0] or 0)
            src_w = int(source_shape[1] or 0)
        if src_w <= 0 or src_h <= 0:
            src_w, src_h = tile_w, tile_h

        try:
            bx = int(round(float(bbox[0])))
            by = int(round(float(bbox[1])))
            bw = int(round(float(bbox[2])))
            bh = int(round(float(bbox[3])))
        except (TypeError, ValueError):
            return None

        if bw <= 0 or bh <= 0:
            return None

        bx1 = max(0, min(bx, src_w - 1))
        by1 = max(0, min(by, src_h - 1))
        bx2 = max(bx1 + 1, min(bx + bw, src_w))
        by2 = max(by1 + 1, min(by + bh, src_h))

        scale_x = tile_w / float(src_w)
        scale_y = tile_h / float(src_h)
        px1 = tile_x1 + int(round(bx1 * scale_x))
        py1 = tile_y1 + int(round(by1 * scale_y))
        px2 = tile_x1 + int(round(bx2 * scale_x))
        py2 = tile_y1 + int(round(by2 * scale_y))

        px1 = max(tile_x1 + 1, min(px1, tile_x2 - 2))
        py1 = max(tile_y1 + 1, min(py1, tile_y2 - 2))
        px2 = max(px1 + 1, min(px2, tile_x2 - 1))
        py2 = max(py1 + 1, min(py2, tile_y2 - 1))
        return px1, py1, px2, py2

    def _format_confidence_percent(self, confidence, decimals=1):
        try:
            confidence_value = float(confidence)
        except (TypeError, ValueError):
            confidence_value = 0.0

        confidence_value = max(0.0, min(1.0, confidence_value))
        percent = confidence_value * 100.0
        multiplier = 10 ** max(0, int(decimals))
        # Truncate instead of rounding so displayed confidence never rounds up.
        truncated = int(percent * multiplier) / float(multiplier)
        return f"{truncated:.{decimals}f}%"

    def _append_ai_metric(self, metric_payload):
        if not isinstance(metric_payload, dict):
            return
        try:
            os.makedirs(os.path.dirname(self._ai_metrics_path), exist_ok=True)
            line = json.dumps(metric_payload, separators=(",", ":"), ensure_ascii=True)
            with self._ai_metrics_lock:
                with open(self._ai_metrics_path, "a", encoding="utf-8") as metric_file:
                    metric_file.write(line + "\n")
        except Exception as e:
            logger.warning("AI metric write failed: %s", e)

    def _update_weight_transition_state(self, weight_kg, now_ts=None):
        current_ts = time.time() if now_ts is None else float(now_ts)
        try:
            current_weight = max(0.0, float(weight_kg))
        except (TypeError, ValueError):
            current_weight = 0.0

        previous_weight = max(0.0, float(self._last_weight_kg or 0.0))
        weight_delta = abs(current_weight - previous_weight)
        crossed_empty = (
            (previous_weight <= self._weight_empty_threshold_kg < current_weight)
            or (current_weight <= self._weight_empty_threshold_kg < previous_weight)
        )
        if weight_delta >= self._weight_change_threshold_kg or crossed_empty:
            self._last_weight_transition_ts = current_ts

        self._last_weight_kg = current_weight

    def _log_manual_assist(self, selected_product, source="quick_select"):
        if not selected_product:
            return

        detailed = self._latest_ai_result if isinstance(self._latest_ai_result, dict) else {}
        metric = {
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "event": "manual_assist",
            "source": str(source),
            "selected_product": str(selected_product),
            "mode_before": str(self._mode),
            "current_product_before": self.current_product,
            "weight_kg": float(self._last_weight_kg or 0.0),
            "recent_weight_transition": self._is_recent_weight_transition(),
            "ai_fused_label": detailed.get("fused_label"),
            "ai_fused_confidence": float(detailed.get("fused_confidence") or 0.0),
            "ai_pipeline_mode": detailed.get("pipeline_mode") or "unknown",
        }
        self._append_ai_metric(metric)

    def _capture_manual_training_frames(self):
        try:
            raw_frames = self._get_ai_frames()
        except Exception as e:
            logger.warning("Manual training frame capture failed: %s", e)
            return []

        captured = []
        for frame in raw_frames[:3]:
            if frame is None:
                continue
            try:
                captured.append(frame.copy())
            except Exception:
                continue
        return captured

    def _queue_manual_training_sample(self, product_name):
        if self._mode != "MANUAL":
            return
        product_label = str(product_name or "").strip()
        if not product_label:
            return

        frames = self._capture_manual_training_frames()
        if not frames:
            return

        existing = self._pending_manual_training_frames.get(product_label, [])
        existing.extend(frames)
        if len(existing) > self._max_manual_training_frames_per_product:
            existing = existing[-self._max_manual_training_frames_per_product :]
        self._pending_manual_training_frames[product_label] = existing

    def _run_post_sale_manual_training(self, training_jobs, transaction_id):
        if not training_jobs:
            return

        trained_products = 0
        trained_frames = 0
        failed_products = 0

        for label, frames in training_jobs:
            if not label or not frames:
                continue
            try:
                message = self.ai.capture_training_data(label, frames)
                trained_products += 1
                trained_frames += len(frames)
                logger.info("Post-sale manual training for %s: %s", label, message)
            except Exception as e:
                failed_products += 1
                logger.warning("Post-sale manual training failed for %s: %s", label, e)

        self._append_ai_metric({
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "event": "manual_post_sale_training",
            "transaction_id": str(transaction_id or ""),
            "trained_products": int(trained_products),
            "trained_frames": int(trained_frames),
            "failed_products": int(failed_products),
        })

    def _is_recent_weight_transition(self, now_ts=None):
        current_ts = time.time() if now_ts is None else float(now_ts)
        return (current_ts - float(self._last_weight_transition_ts or 0.0)) <= self._weight_transition_window_s

    def _log_ai_cycle_metrics(self, detailed_result, telemetry_context, action):
        if self._mode != "AUTO":
            return

        context = telemetry_context if isinstance(telemetry_context, dict) else {}
        result = detailed_result if isinstance(detailed_result, dict) else {}
        action_info = action if isinstance(action, dict) else {}

        per_frame_predictions = result.get("per_frame_predictions") or []
        per_camera = []
        for prediction in per_frame_predictions:
            if not isinstance(prediction, dict):
                continue
            try:
                camera_index = int(prediction.get("frame_index", len(per_camera)))
            except (TypeError, ValueError):
                camera_index = len(per_camera)
            per_camera.append({
                "camera_index": camera_index,
                "label": prediction.get("label"),
                "confidence": float(prediction.get("confidence") or 0.0),
                "active": bool(prediction.get("active")),
            })

        cycle_started_at = float(context.get("cycle_started_at") or 0.0)
        consume_started_at = time.time()
        cycle_latency_ms = ((consume_started_at - cycle_started_at) * 1000.0) if cycle_started_at > 0 else None
        recent_weight_transition = bool(context.get("recent_weight_transition", False))

        selected_before = context.get("selected_before")
        selected_after = action_info.get("selected_product", self.current_product)
        selected_changed = bool(action_info.get("selected_changed", False))
        false_switch = (
            selected_changed
            and bool(selected_before)
            and bool(selected_after)
            and selected_before != selected_after
            and not recent_weight_transition
        )

        metric = {
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "event": "ai_cycle",
            "mode": self._mode,
            "pipeline_mode": result.get("pipeline_mode") or "unknown",
            "fused_label": result.get("fused_label"),
            "fused_confidence": float(result.get("fused_confidence") or 0.0),
            "active_frame_count": int(result.get("active_frame_count") or 0),
            "camera_count": int(context.get("camera_count") or self._last_camera_count),
            "weight_kg": float(context.get("weight_kg") or 0.0),
            "recent_weight_transition": recent_weight_transition,
            "ai_inference_ms": float(result.get("ai_inference_ms") or 0.0),
            "cycle_latency_ms": float(cycle_latency_ms) if cycle_latency_ms is not None else None,
            "decision": action_info.get("decision"),
            "selected_before": selected_before,
            "selected_after": selected_after,
            "selected_changed": selected_changed,
            "false_switch": false_switch,
            "fast_lock": bool(action_info.get("fast_lock", False)),
            "fallback_frame_count": len(result.get("fallback_frame_indices") or []),
            "vote_counts": result.get("vote_counts") or {},
            "per_camera": per_camera,
        }
        self._append_ai_metric(metric)

    def _draw_camera_overlays(self, composite_frame, camera_count):
        if composite_frame is None:
            return composite_frame

        frame = composite_frame.copy()
        detailed = self._latest_ai_result or {}
        per_frame_predictions = detailed.get('per_frame_predictions') or []
        fused_label = str(detailed.get('fused_label') or "").strip()
        fused_label_lower = fused_label.lower()

        draw_count = int(camera_count or 0)
        if draw_count <= 0:
            draw_count = len(per_frame_predictions)
        rects = self._get_camera_tile_rects(frame.shape, draw_count)
        if not rects:
            return frame

        prediction_map = {}
        for idx, pred in enumerate(per_frame_predictions):
            if not isinstance(pred, dict):
                continue
            frame_index = pred.get('frame_index', idx)
            try:
                prediction_map[int(frame_index)] = pred
            except (TypeError, ValueError):
                continue

        bg_labels = {"background", "empty", "none"}
        winner_color = (96, 174, 39)
        mismatch_color = (34, 126, 230)
        neutral_color = (189, 195, 199)
        label_bg = (44, 62, 80)
        font = cv2.FONT_HERSHEY_SIMPLEX
        frame_h = frame.shape[0] if frame is not None else 0
        tile_h = max(1, int(frame_h / 2)) if len(rects) >= 3 else max(1, frame_h)
        font_scale = max(0.70, min(1.30, tile_h / 240.0))
        thickness = 2 if font_scale >= 0.85 else 1
        pad_x = max(10, int(8 * font_scale))
        pad_y = max(10, int(8 * font_scale))

        for i, (x1, y1, x2, y2) in enumerate(rects):
            pred = prediction_map.get(i)
            status_text = f"Cam {i+1}: scanning"
            status_color = neutral_color
            if pred:
                pred_label = str(pred.get('label') or "").strip()
                pred_label_lower = pred_label.lower()
                pred_active = bool(pred.get('active'))
                try:
                    pred_confidence = float(pred.get('confidence') or 0.0)
                except (TypeError, ValueError):
                    pred_confidence = 0.0

                if (not pred_active) or (not pred_label) or pred_label_lower in bg_labels:
                    status_text = f"Cam {i+1}: no item"
                else:
                    status_text = f"Cam {i+1}: {pred_label} {self._format_confidence_percent(pred_confidence)}"
                    if fused_label and pred_label_lower == fused_label_lower:
                        status_color = winner_color
                    elif fused_label and pred_label_lower != fused_label_lower:
                        status_color = mismatch_color

            (text_w, text_h), baseline = cv2.getTextSize(status_text, font, font_scale, thickness)
            text_x = x1 + pad_x
            text_y = y1 + text_h + pad_y
            cv2.rectangle(
                frame,
                (text_x - pad_x // 2, text_y - text_h - pad_y // 2),
                (min(x2 - 4, text_x + text_w + pad_x // 2), text_y + baseline + pad_y // 2),
                label_bg,
                -1
            )
            cv2.putText(frame, status_text, (text_x, text_y), font, font_scale, status_color, thickness, cv2.LINE_AA)

        return frame

    def toggle_mode(self):
        self._mode = "MANUAL" if self._mode == "AUTO" else "AUTO"
        self._apply_mode_ui()
        if self._mode == "AUTO":
            # Clear manual lock when returning to auto
            self.current_product = None
            self.current_price = 0.0
            self.lbl_selected.config(text="None")

    def _set_auto_status(self, status_text, color):
        self._auto_status_text = status_text
        self._auto_status_color = color
        if self._mode == "AUTO":
            self._apply_mode_ui()

    def _apply_mode_ui(self):
        # SAFETY CHECK: Ensure the UI hasn't been destroyed before attempting to configure it
        if not hasattr(self, 'btn_mode') or not self.btn_mode.winfo_exists():
            return
            
        if self._mode == "AUTO":
            self.btn_mode.config(text="⚡ AUTO MODE", bg="#27ae60")
            status_text = self._auto_status_text or "Ready"
            self.lbl_sel_header.config(text="⚡ AUTO — SELECTED ITEM", fg="#27ae60", bg="#f8f9fa")
            self.lbl_sel_status.config(text=status_text, fg=self._auto_status_color, bg="#f8f9fa")
            self.lbl_selected.config(bg="#f8f9fa")
            self.sel_frame.config(bg="#f8f9fa")
        else:
            self.btn_mode.config(text="✋ MANUAL MODE", bg="#e67e22")
            self.lbl_sel_header.config(text="✋ MANUAL — SELECTED ITEM", fg="#e67e22", bg="#fff8f0")
            self.lbl_sel_status.config(text="Manual selection active", fg="#e67e22", bg="#fff8f0")
            self.lbl_selected.config(bg="#fff8f0")
            self.sel_frame.config(bg="#fff8f0")

    def update_loop(self):
        if not self.running: return
        try:
            frame = self.camera.get_ui_frame()
            if frame is not None and self.cam_container.winfo_exists():
                try:
                    ai_gate_weight = float(self.scale.get_weight())
                except Exception:
                    ai_gate_weight = 0.0
                self._update_weight_transition_state(ai_gate_weight)

                ai_frames = self._get_ai_frames()
                self._last_camera_count = len(ai_frames)
                self._last_ai_frame_shapes = [raw_frame.shape[:2] for raw_frame in ai_frames]

                self._ai_frame_counter += 1
                if self._ai_frame_counter >= self._ai_inference_interval and self._mode == "AUTO" and not self._is_predicting:
                    self._ai_frame_counter = 0
                    self._is_predicting = True

                    if ai_gate_weight < 0.01:
                        self._prediction_history.clear()
                        self.current_product = None
                        self.current_price = 0.0
                        self.lbl_selected.config(text="None")
                        self._set_auto_status("Scanning / no product", "#7f8c8d")
                        self._latest_ai_result['object_detections'] = []
                        self._latest_ai_result['per_frame_detections'] = []
                        self._latest_ai_result['per_frame_predictions'] = []
                        self._is_predicting = False
                    else:

                        ai_status = self._get_ai_runtime_status()
                        status_known = bool(ai_status)
                        ai_model_ready = bool(ai_status.get("feature_extractor_ready", True)) if status_known else True
                        profiles_loaded = int(ai_status.get("profiles_loaded") or 0) if status_known else 1

                        if not ai_model_ready:
                            self._set_auto_status("AI unavailable", "#c0392b")
                            self._latest_ai_result['object_detections'] = []
                            self._latest_ai_result['per_frame_detections'] = []
                            self._latest_ai_result['per_frame_predictions'] = []
                            self._is_predicting = False
                        elif profiles_loaded <= 0:
                            self._set_auto_status("No AI profiles", "#e67e22")
                            self._latest_ai_result['object_detections'] = []
                            self._latest_ai_result['per_frame_detections'] = []
                            self._latest_ai_result['per_frame_predictions'] = []
                            self._is_predicting = False
                        elif not ai_frames:
                            self._set_auto_status("Scanning", "#7f8c8d")
                            self._latest_ai_result['object_detections'] = []
                            self._latest_ai_result['per_frame_detections'] = []
                            self._latest_ai_result['per_frame_predictions'] = []
                            self._is_predicting = False
                        else:
                            telemetry_context = {
                                "cycle_started_at": time.time(),
                                "camera_count": len(ai_frames),
                                "weight_kg": ai_gate_weight,
                                "selected_before": self.current_product,
                                "recent_weight_transition": self._is_recent_weight_transition(),
                            }

                            def _run_ai(context=telemetry_context):
                                ai_start = time.perf_counter()
                                try:
                                    detailed_result = self.ai.predict_product_detailed(ai_frames)
                                except Exception as ai_error:
                                    logger.warning("AI prediction error: %s", ai_error)
                                    detailed_result = None

                                ai_inference_ms = (time.perf_counter() - ai_start) * 1000.0
                                if isinstance(detailed_result, dict):
                                    detailed_result["ai_inference_ms"] = ai_inference_ms

                                self.root.after(
                                    0,
                                    lambda result=detailed_result, ctx=context: self._consume_ai_result(result, ctx)
                                )

                            threading.Thread(target=_run_ai, daemon=True).start()

                w = self.cam_container.winfo_width()
                h = self.cam_container.winfo_height()
                if w > 10 and h > 10:
                    frame_with_overlay = self._draw_camera_overlays(frame, self._last_camera_count)
                    img = self.smart_resize(frame_with_overlay, w, h)
                    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                    img = Image.fromarray(img)
                    imgtk = ImageTk.PhotoImage(image=img)
                    self.cam_label.imgtk = imgtk
                    self.cam_label.configure(image=imgtk)
        except Exception as e:
            logger.warning("Camera/AI loop error: %s", e)
        
        weight = max(0.0, float(self._last_weight_kg or 0.0))
        self.lbl_weight.config(text=f"{weight:.2f} kg")

        # Auto-clear selected product when scale is empty (AUTO mode only)
        if self._mode == "AUTO" and weight <= 0.005 and self.current_product is not None:
            self.current_product = None
            self.current_price = 0.0
            self.lbl_selected.config(text="None")
            self._product_lock_timestamp = 0.0
            self._switch_candidate_label = None
            self._switch_candidate_count = 0

        if hasattr(self.root, 'customer_display'):
            current_name = self.current_product if self.current_product else "Place Item"
            cart_sum = sum(i['total'] for i in self.cart)
            self.root.customer_display.update_view(
                current_name,
                weight,
                cart_sum,
                self.current_price,
                list(self.cart)
            )

        self.root.after(75, self.update_loop)

    def _consume_ai_result(self, detailed_result, telemetry_context=None):
        # SAFETY CHECK: Don't process results if the system is shutting down
        if not self.running:
            self._is_predicting = False
            return

        action = None
        try:
            action = self._process_ai_result(detailed_result)
        finally:
            self._is_predicting = False

        self._log_ai_cycle_metrics(detailed_result, telemetry_context, action)

    def _process_ai_result(self, detailed_result):
        _BG = {"background", "empty", "none"}

        result = detailed_result if isinstance(detailed_result, dict) else {}
        fused_label = result.get('fused_label')
        fused_confidence = float(result.get('fused_confidence') or 0.0)
        vote_counts = result.get('vote_counts') or {}
        per_frame_predictions = result.get('per_frame_predictions') or []
        active_frame_count = int(result.get('active_frame_count') or 0)
        object_detections = result.get('object_detections') or []
        per_frame_detections = result.get('per_frame_detections') or []

        self._latest_ai_result = {
            'fused_label': fused_label,
            'fused_confidence': fused_confidence,
            'per_frame_predictions': per_frame_predictions,
            'vote_counts': vote_counts,
            'active_frame_count': active_frame_count,
            'object_detections': object_detections,
            'per_frame_detections': per_frame_detections
        }

        if self._mode != "AUTO":
            return {
                "decision": "manual_skip",
                "selected_changed": False,
                "selected_product": self.current_product,
                "fast_lock": False,
            }

        starting_product = self.current_product

        camera_labels = set()
        for prediction in per_frame_predictions:
            if not isinstance(prediction, dict):
                continue
            if not bool(prediction.get('active')):
                continue
            prediction_label = str(prediction.get('label') or "").strip().lower()
            if not prediction_label or prediction_label in _BG:
                continue
            camera_labels.add(prediction_label)

        has_camera_label = len(camera_labels) > 0

        winning_votes = int(vote_counts.get(fused_label, 0)) if fused_label else 0
        required_votes = 2 if active_frame_count >= 2 else 1
        valid_label = bool(fused_label) and fused_label.lower() not in _BG
        confidence_ok = fused_confidence > 0.65
        agreement_ok = winning_votes >= required_votes
        now_ts = time.time()
        switching_label = bool(self.current_product) and bool(fused_label) and (fused_label != self.current_product)
        recent_weight_transition = self._is_recent_weight_transition(now_ts)
        adaptive_switch_confidence = (
            max(0.90, self._switch_label_min_confidence - 0.03)
            if recent_weight_transition
            else self._switch_label_min_confidence
        )
        adaptive_switch_votes = (
            max(2, self._switch_label_min_votes - 1)
            if recent_weight_transition
            else self._switch_label_min_votes
        )
        switch_votes_required = min(active_frame_count, adaptive_switch_votes)
        switch_weight_ok = (not switching_label) or recent_weight_transition
        switch_hold_ok = (not switching_label) or ((now_ts - self._product_lock_timestamp) >= self._min_lock_hold_seconds)
        switch_base_ok = (
            (not switching_label)
            or (
                switch_weight_ok
                and
                active_frame_count >= 2
                and fused_confidence >= adaptive_switch_confidence
                and winning_votes >= switch_votes_required
            )
        )

        if switching_label and switch_base_ok and switch_hold_ok:
            if fused_label == self._switch_candidate_label:
                self._switch_candidate_count += 1
            else:
                self._switch_candidate_label = fused_label
                self._switch_candidate_count = 1
        else:
            self._switch_candidate_label = None
            self._switch_candidate_count = 0

        switch_consecutive_ok = (not switching_label) or (self._switch_candidate_count >= self._switch_required_consecutive)
        switch_gate_ok = switch_base_ok and switch_hold_ok and switch_consecutive_ok

        gate_passed = (
            valid_label and
            confidence_ok and
            active_frame_count > 0 and
            agreement_ok and
            switch_gate_ok
        )

        # Fast-lock only when all active cameras agree with very high confidence.
        fast_lock_confidence_required = self._fast_lock_min_confidence
        if switching_label:
            fast_lock_confidence_required = max(
                fast_lock_confidence_required,
                adaptive_switch_confidence,
            )
        fast_lock_ok = (
            valid_label and
            active_frame_count >= self._fast_lock_min_cameras and
            switch_weight_ok and
            winning_votes == active_frame_count and
            fused_confidence >= fast_lock_confidence_required
        )

        if fast_lock_ok and fused_label != self.current_product:
            self.current_product = fused_label
            self.current_price = self.db.get_product_price(fused_label)
            self._product_lock_timestamp = now_ts
            self._switch_candidate_label = None
            self._switch_candidate_count = 0
            self.lbl_selected.config(text=f"{fused_label} ({self._format_confidence_percent(fused_confidence)})")
            # Seed history so fallback voting remains stable after instant lock.
            self._prediction_history.clear()
            for _ in range(4):
                self._prediction_history.append(fused_label)
            self._set_auto_status(
                f"Fast lock {winning_votes}/{active_frame_count} ({self._format_confidence_percent(fused_confidence)})",
                "#27ae60"
            )
            return {
                "decision": "fast_lock",
                "selected_changed": starting_product != self.current_product,
                "selected_product": self.current_product,
                "fast_lock": True,
            }

        if gate_passed:
            self._prediction_history.append(fused_label)
            if active_frame_count >= 2:
                self._set_auto_status(f"Agreement {winning_votes}/{active_frame_count}", "#27ae60")
            else:
                self._set_auto_status("Single-cam mode", "#27ae60")
            if self.current_product == fused_label:
                self.lbl_selected.config(text=f"{fused_label} ({self._format_confidence_percent(fused_confidence)})")
        else:
            self._prediction_history.append(None)
            if not has_camera_label:
                self._set_auto_status("Scanning / no product", "#7f8c8d")
            elif not valid_label:
                self._set_auto_status("No product", "#7f8c8d")
            elif not confidence_ok:
                self._set_auto_status(f"Low confidence {self._format_confidence_percent(fused_confidence)}", "#e67e22")
            elif switching_label and not switch_gate_ok:
                if not switch_weight_ok:
                    self._set_auto_status("Waiting for weight change", "#e67e22")
                elif not switch_hold_ok:
                    self._set_auto_status("Holding current item", "#e67e22")
                else:
                    self._set_auto_status(
                        f"Confirm switch {self._switch_candidate_count}/{self._switch_required_consecutive}",
                        "#e67e22"
                    )
            else:
                if active_frame_count >= 3:
                    self._set_auto_status(f"Need 2-of-3 ({winning_votes}/{active_frame_count})", "#e67e22")
                else:
                    self._set_auto_status(f"Disagreement {winning_votes}/{active_frame_count}", "#e67e22")

        # Require a majority of the rolling window (≥4 of 7) to agree
        if len(self._prediction_history) >= 4:
            counts = Counter(self._prediction_history)
            top_label, top_count = counts.most_common(1)[0]
            if top_count >= 4:
                if top_label is None:
                    # Majority says background → clear product
                    self.current_product = None
                    self.current_price = 0.0
                    self.lbl_selected.config(text="None")
                    self._product_lock_timestamp = 0.0
                    self._switch_candidate_label = None
                    self._switch_candidate_count = 0
                elif top_label != self.current_product:
                    self.current_product = top_label
                    self.current_price = self.db.get_product_price(top_label)
                    self._product_lock_timestamp = now_ts
                    self._switch_candidate_label = None
                    self._switch_candidate_count = 0
                    if gate_passed and top_label == fused_label:
                        self.lbl_selected.config(text=f"{top_label} ({self._format_confidence_percent(fused_confidence)})")
                    else:
                        self.lbl_selected.config(text=top_label)

        return {
            "decision": "gate_pass" if gate_passed else "gate_block",
            "selected_changed": starting_product != self.current_product,
            "selected_product": self.current_product,
            "fast_lock": False,
        }

    def select_product(self, name):
        # Tapping Quick Select always locks into MANUAL mode
        if self._mode != "MANUAL":
            self._mode = "MANUAL"
            self._apply_mode_ui()
        self._log_manual_assist(name, source="quick_select")
        self._prediction_history.clear()  # discard stale AI votes
        self.current_product = name
        self.current_price = self.db.get_product_price(name)
        self._product_lock_timestamp = time.time()
        self._switch_candidate_label = None
        self._switch_candidate_count = 0
        self.lbl_selected.config(text=name)

    def _show_floating_alert(self, title, message, level="warning"):
        color_map = {
            "warning": config.WARNING_COLOR,
            "danger": config.DANGER_COLOR,
            "info": config.ACCENT_COLOR
        }
        header_color = color_map.get(level, config.WARNING_COLOR)

        popup = tk.Toplevel(self.root)
        popup.overrideredirect(True)
        popup.attributes('-topmost', True)
        popup.transient(self.root)

        w, h = 430, 210
        popup.geometry(f"{w}x{h}+{(config.SCREEN_MAIN_W-w)//2}+{(config.SCREEN_MAIN_H-h)//2}")
        popup.configure(bg=config.THEME_COLOR)

        inner = tk.Frame(popup, bg="white")
        inner.pack(fill=tk.BOTH, expand=True, padx=3, pady=3)

        header = tk.Frame(inner, bg=header_color, pady=14)
        header.pack(fill=tk.X)
        tk.Label(
            header,
            text=title,
            font=("Segoe UI", 14, "bold"),
            bg=header_color,
            fg="white"
        ).pack()

        tk.Label(
            inner,
            text=message,
            font=("Segoe UI", 12),
            bg="white",
            fg=config.THEME_COLOR,
            wraplength=360,
            justify="center"
        ).pack(expand=True, pady=10)

        tk.Button(
            inner,
            text="OK",
            font=("Segoe UI", 12, "bold"),
            bg=header_color,
            fg="white",
            relief="flat",
            activebackground=header_color,
            padx=24,
            pady=8,
            command=popup.destroy
        ).pack(pady=(0, 14))

        popup.grab_set()

    def add_to_cart(self):
        weight = self.scale.get_weight()
        if not self.current_product:
            self._show_floating_alert("Missing Info", "Please select a product first.", level="warning")
            return

        calc_weight = round(float(weight or 0.0), 2)
        if calc_weight < 0.01:
            self._show_floating_alert("Weight Error", "Scale is empty.", level="warning")
            return

        price = self.current_price or self.db.get_product_price(self.current_product)
        total = round(calc_weight * price, 2)
        found = False
        for item in self.cart:
            if item['name'] == self.current_product:
                item['weight'] = round(item['weight'] + calc_weight, 2)
                item['total'] = round(item['total'] + total, 2)
                found = True
                break
        if not found:
            self.cart.append({"name": self.current_product, "weight": calc_weight, "total": total})

        self._queue_manual_training_sample(self.current_product)
        self.refresh_cart_tree()
        self.update_total_label()
        
        # Reset current product selection only — mode stays as the user set it
        self._prediction_history.clear()  # fresh start for next item
        self.current_product = None
        self.current_price = 0.0
        self.lbl_selected.config(text="None")

    def void_item(self):
        selected_item = self.tree.selection()
        if not selected_item:
            self._show_floating_alert("Selection Error", "Please select an item to remove.", level="warning")
            return
        item_values = self.tree.item(selected_item, "values")
        item_name = item_values[0]

        # Custom styled confirmation dialog
        void_win = tk.Toplevel(self.root)
        void_win.overrideredirect(True)
        void_win.attributes('-topmost', True)
        void_win.transient(self.root)
        vw, vh = 420, 240
        void_win.geometry(f"{vw}x{vh}+{(config.SCREEN_MAIN_W-vw)//2}+{(config.SCREEN_MAIN_H-vh)//2}")
        void_win.configure(bg=config.THEME_COLOR)

        inner = tk.Frame(void_win, bg="white")
        inner.pack(fill=tk.BOTH, expand=True, padx=3, pady=3)

        hdr = tk.Frame(inner, bg=config.DANGER_COLOR, pady=14)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text="⚠  Confirm Void Item",
                 font=("Segoe UI", 14, "bold"), bg=config.DANGER_COLOR, fg="white").pack()

        tk.Label(inner, text=f"Remove  \"{item_name}\"  from cart?",
                 font=("Segoe UI", 13), bg="white", fg=config.THEME_COLOR,
                 wraplength=360, justify="center").pack(expand=True, pady=10)

        btn_row = tk.Frame(inner, bg="white", padx=30, pady=14)
        btn_row.pack(fill=tk.X)
        btn_row.columnconfigure(0, weight=1)
        btn_row.columnconfigure(1, weight=1)

        def _do_void():
            void_win.destroy()
            self.cart = [item for item in self.cart if item['name'] != item_name]
            self._pending_manual_training_frames.pop(item_name, None)
            self.refresh_cart_tree()
            self.update_total_label()

        tk.Button(btn_row, text="✔  YES, REMOVE",
                  font=("Segoe UI", 12, "bold"),
                  bg=config.DANGER_COLOR, fg="white", relief="flat",
                  activebackground="#e74c3c", pady=10,
                  command=_do_void).grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        tk.Button(btn_row, text="✖  CANCEL",
                  font=("Segoe UI", 12, "bold"),
                  bg="#ecf0f1", fg=config.THEME_COLOR, relief="flat",
                  activebackground="#d5d8dc", pady=10,
                  command=void_win.destroy).grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        void_win.grab_set()

    def refresh_cart_tree(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for item in self.cart:
            self.tree.insert("", "end", values=(
                item['name'], 
                f"{item['weight']:.2f}", 
                f"{item['total']:.2f}"
            ))

    def update_total_label(self):
        cart_sum = sum(i['total'] for i in self.cart)
        self.lbl_total.config(text=f"Total: ₱ {cart_sum:.2f}")

    def checkout(self):
        if not self.cart: return
        total = sum(i['total'] for i in self.cart)

        pay_win = tk.Toplevel(self.root)
        pay_win.overrideredirect(True)
        pay_win.attributes('-topmost', True)
        pay_win.transient(self.root)

        w, h = 640, 660
        sw, sh = config.SCREEN_MAIN_W, config.SCREEN_MAIN_H
        pay_win.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
        # Dark border like GCash verify dialog
        pay_win.configure(bg=config.THEME_COLOR)

        # Inner content — 3px inset shows the dark border on all sides
        pay_inner = tk.Frame(pay_win, bg="#f4f6f9")
        pay_inner.pack(fill=tk.BOTH, expand=True, padx=3, pady=3)

        # ── Header bar ───────────────────────────────────────────────────
        header = tk.Frame(pay_inner, bg=config.THEME_COLOR, pady=14, padx=20)
        header.pack(fill=tk.X)

        tk.Label(header, text="PAYMENT PROCESSING", font=("Segoe UI", 15, "bold"),
                 bg=config.THEME_COLOR, fg="white").pack(side=tk.LEFT)

        tk.Button(header, text="✖  CANCEL", font=("Segoe UI", 11, "bold"),
                  bg=config.DANGER_COLOR, fg="white", relief="flat", padx=12, pady=4,
                  activebackground="#e74c3c", command=pay_win.destroy).pack(side=tk.RIGHT)

        # ── Amount badge ─────────────────────────────────────────────────
        amt_row = tk.Frame(pay_inner, bg="#f4f6f9", pady=14)
        amt_row.pack(fill=tk.X)
        tk.Label(amt_row, text="TOTAL AMOUNT DUE", font=("Segoe UI", 11),
                 bg="#f4f6f9", fg="#7f8c8d").pack()
        tk.Label(amt_row, text=f"₱ {total:.2f}", font=("Segoe UI", 42, "bold"),
                 bg="#f4f6f9", fg=config.THEME_COLOR).pack()

        # ── Bottom buttons (packed first so expand=True body doesn't steal space) ──
        bot = tk.Frame(pay_inner, bg="#f4f6f9")
        bot.pack(side=tk.BOTTOM, fill=tk.X, padx=20, pady=(0, 14))

        # ── Body: left card + right numpad ────────────────────────────────
        body = tk.Frame(pay_inner, bg="#f4f6f9")
        body.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 6))
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, minsize=270)
        body.rowconfigure(0, weight=1)

        # Left card
        left_card = tk.Frame(body, bg="white", relief="solid", bd=1, padx=18, pady=18)
        left_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        tk.Label(left_card, text="Cash Tendered", font=("Segoe UI", 11),
                 bg="white", fg="#7f8c8d").pack(anchor="w")
        self.cash_var = tk.StringVar(value="")
        self._cash_display = tk.Label(left_card, textvariable=self.cash_var,
                                      font=("Segoe UI", 28, "bold"),
                                      bg="#f0f3f7", fg=config.THEME_COLOR,
                                      anchor="e", relief="flat", padx=10, pady=8)
        self._cash_display.pack(fill=tk.X, pady=(4, 18))

        divider = tk.Frame(left_card, bg="#ecf0f1", height=2)
        divider.pack(fill=tk.X)

        tk.Label(left_card, text="Change Due", font=("Segoe UI", 11),
                 bg="white", fg="#7f8c8d").pack(anchor="w", pady=(14, 0))
        self.change_var = tk.StringVar(value="—")
        self._change_lbl = tk.Label(left_card, textvariable=self.change_var,
                 font=("Segoe UI", 34, "bold"),
                 bg="white", fg="#bdc3c7", anchor="e")
        self._change_lbl.pack(fill=tk.X)

        # Right numpad card
        pad_card = tk.Frame(body, bg="white", relief="solid", bd=1, padx=8, pady=8)
        pad_card.grid(row=0, column=1, sticky="nsew")
        for ci in range(3): pad_card.columnconfigure(ci, weight=1)
        for ri in range(5): pad_card.rowconfigure(ri, weight=1)

        self.current_cash_str = ""
        self.btn_confirm = None

        def update_calc():
            try:
                tendered = float(self.current_cash_str) if self.current_cash_str else 0.0
                self.cash_var.set(f"₱ {tendered:.2f}")
                change = tendered - total
                if change >= 0:
                    self.change_var.set(f"₱ {change:.2f}")
                    self._change_lbl.config(fg=config.SUCCESS_COLOR)
                    if self.btn_confirm:
                        self.btn_confirm.config(state="normal", bg=config.SUCCESS_COLOR)
                else:
                    self.change_var.set("—")
                    self._change_lbl.config(fg="#bdc3c7")
                    if self.btn_confirm:
                        self.btn_confirm.config(state="disabled", bg="#bdc3c7")
            except Exception:
                self.cash_var.set("Error")

        def press(key):
            if key == 'C':
                self.current_cash_str = ""
            elif key in ('BACK', '⌫'):
                self.current_cash_str = self.current_cash_str[:-1]
            else:
                self.current_cash_str += key if len(self.current_cash_str) < 8 else ""
            update_calc()

        keys = ['7', '8', '9', '4', '5', '6', '1', '2', '3', '0', '.', '⌫']
        r, c = 0, 0
        for k in keys:
            tk.Button(pad_card, text=k, font=("Segoe UI", 18, "bold"),
                      bg="white", fg=config.THEME_COLOR, relief="flat",
                      activebackground="#ecf0f1",
                      command=lambda x=k: press(x)).grid(
                          row=r, column=c, sticky="nsew", padx=2, pady=2)
            c += 1
            if c > 2: c = 0; r += 1
        tk.Button(pad_card, text="CLEAR", font=("Segoe UI", 12, "bold"),
                  bg="#ecf0f1", fg="#7f8c8d", relief="flat",
                  command=lambda: press('C')).grid(
                      row=r, column=0, columnspan=3, sticky="nsew", padx=2, pady=2)

        # ── Bottom button contents ────────────────────────────────────────
        def do_pay_cash():
            try:
                tendered = float(self.current_cash_str)
                if tendered >= total:
                    self.finalize(total, tendered, "Cash")
                    pay_win.destroy()
            except Exception:
                pass

        def do_pay_qr():
            if hasattr(self.root, 'customer_display'):
                self.root.customer_display.show_qr(amount=total)

            # Custom styled GCash verification dialog
            verify_win = tk.Toplevel(pay_win)
            verify_win.overrideredirect(True)
            verify_win.attributes('-topmost', True)
            vw, vh = 480, 280
            verify_win.geometry(f"{vw}x{vh}+{(sw-vw)//2}+{(sh-vh)//2}")
            # Border: highlightthickness on the window gives a visible outline
            verify_win.configure(bg=config.THEME_COLOR,
                                 highlightbackground=config.THEME_COLOR,
                                 highlightthickness=3)

            # Inner content sits inside a 3-px inset so the border shows on all sides
            inner = tk.Frame(verify_win, bg="white")
            inner.pack(fill=tk.BOTH, expand=True, padx=3, pady=3)

            vheader = tk.Frame(inner, bg="#00a651", pady=16)
            vheader.pack(fill=tk.X)
            tk.Label(vheader, text="GCash Payment Verification",
                     font=("Segoe UI", 14, "bold"), bg="#00a651", fg="white").pack()

            tk.Label(inner,
                     text="Did you receive the GCash\npayment successfully?",
                     font=("Segoe UI", 15), bg="white", fg=config.THEME_COLOR,
                     justify="center").pack(expand=True)

            btn_row = tk.Frame(inner, bg="white", padx=30, pady=14)
            btn_row.pack(fill=tk.X)
            btn_row.columnconfigure(0, weight=1)
            btn_row.columnconfigure(1, weight=1)

            def _confirm():
                verify_win.destroy()
                self.finalize(total, None, "GCash")
                pay_win.destroy()

            def _deny():
                verify_win.destroy()
                if hasattr(self.root, 'customer_display'):
                    self.root.customer_display.hide_qr()

            tk.Button(btn_row, text="✔  YES, RECEIVED",
                      font=("Segoe UI", 13, "bold"),
                      bg="#00a651", fg="white", relief="flat",
                      activebackground="#009944", pady=10,
                      command=_confirm).grid(row=0, column=0, sticky="nsew", padx=(0, 8))
            tk.Button(btn_row, text="✖  NOT YET",
                      font=("Segoe UI", 13, "bold"),
                      bg=config.DANGER_COLOR, fg="white", relief="flat",
                      activebackground="#e74c3c", pady=10,
                      command=_deny).grid(row=0, column=1, sticky="nsew", padx=(8, 0))

            verify_win.grab_set()

        self.btn_confirm = tk.Button(bot, text="✔  CONFIRM CASH PAYMENT",
                                     font=("Segoe UI", 14, "bold"),
                                     bg="#bdc3c7", fg="white", relief="flat",
                                     state="disabled", pady=12,
                                     command=do_pay_cash)
        self.btn_confirm.pack(fill=tk.X, pady=(0, 8))

        tk.Button(bot, text="📱  PAY VIA GCASH / QR",
                  font=("Segoe UI", 13, "bold"),
                  bg=config.ACCENT_COLOR, fg="white", relief="flat",
                  pady=10, activebackground="#2980b9",
                  command=do_pay_qr).pack(fill=tk.X)

        pay_win.grab_set()

    def show_success_popup(self, t_id):
        popup = tk.Toplevel(self.root)
        popup.overrideredirect(True)
        popup.attributes('-topmost', True)
        popup.transient(self.root)

        pw, ph = 420, 280
        popup.geometry(f"{pw}x{ph}+{(config.SCREEN_MAIN_W-pw)//2}+{(config.SCREEN_MAIN_H-ph)//2}")
        # Dark border matching GCash verify dialog
        popup.configure(bg=config.THEME_COLOR)

        p_inner = tk.Frame(popup, bg="white")
        p_inner.pack(fill=tk.BOTH, expand=True, padx=3, pady=3)

        # Dark header
        hdr = tk.Frame(p_inner, bg=config.SUCCESS_COLOR, pady=18)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text="✔  TRANSACTION COMPLETE",
                 font=("Segoe UI", 16, "bold"), bg=config.SUCCESS_COLOR, fg="white").pack()

        # White body
        body = tk.Frame(p_inner, bg="white")
        body.pack(fill=tk.BOTH, expand=True)

        tk.Label(body, text="Receipt ID", font=("Segoe UI", 10),
                 bg="white", fg="#7f8c8d").pack(pady=(20, 4))

        id_badge = tk.Frame(body, bg="#f0f3f7", relief="solid", bd=1)
        id_badge.pack(padx=40)
        tk.Label(id_badge, text=t_id, font=("Segoe UI", 15, "bold"),
                 bg="#f0f3f7", fg=config.THEME_COLOR, padx=20, pady=8).pack()

        tk.Label(body, text="Receipt printed successfully.",
                 font=("Segoe UI", 11), bg="white", fg="#95a5a6").pack(pady=(12, 0))

        # Auto-close after 4s; close button
        def _close():
            try:
                popup.destroy()
            except Exception:
                pass

        tk.Button(body, text="CLOSE", font=("Segoe UI", 13, "bold"),
                  bg=config.SUCCESS_COLOR, fg="white", relief="flat",
                  padx=24, pady=8, activebackground="#229954",
                  command=_close).pack(pady=14)

        popup.after(4000, _close)

    def finalize(self, total, tendered, payment_method):
        t_id = datetime.datetime.now().strftime("%Y%m%d%H%M%S")

        finalized_product_names = {
            str(item.get('name') or '').strip()
            for item in self.cart
            if isinstance(item, dict)
        }
        training_jobs = []
        for product_name in finalized_product_names:
            frames = self._pending_manual_training_frames.get(product_name) or []
            if frames:
                training_jobs.append((product_name, list(frames)))

        self.db.save_transaction(self.cart, payment_method, t_id, self.current_user)
        for item in self.cart: self.db.deduct_stock(item['name'], item['weight'])
        seller_name = str((self.current_user or {}).get("name") or "").strip()
        try:
            self.printer.print_receipt(
                self.cart,
                total,
                tendered,
                payment_method,
                transaction_id=t_id,
                seller_name=seller_name
            )
        except TypeError as exc:
            if "seller_name" not in str(exc):
                raise
            self.printer.print_receipt(self.cart, total, tendered, payment_method, t_id)

        self._pending_manual_training_frames.clear()
        if training_jobs:
            threading.Thread(
                target=self._run_post_sale_manual_training,
                args=(training_jobs, t_id),
                daemon=True,
            ).start()

        self.cart = []; self.refresh_cart_tree(); self.update_total_label()
        # Clear selection so update_loop doesn't send price_per_kg > 0 and kill the Thank You screen
        self.current_product = None
        self.current_price = 0.0
        self.lbl_selected.config(text="None")
        if hasattr(self.root, 'customer_display'): self.root.customer_display.show_thank_you()
        self.show_success_popup(t_id)

