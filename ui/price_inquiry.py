import tkinter as tk
from tkinter import ttk
import logging
import threading
import config

logger = logging.getLogger(__name__)


class PriceInquiryWindow(tk.Toplevel):
    def __init__(
        self,
        parent,
        db,
        scale,
        camera,
        selection_provider=None,
        ai_engine=None,
        state_callback=None,
        on_open=None,
        on_close=None
    ):
        super().__init__(parent)
        self.title("Price Inquiry")

        # Remove title bar and keep above main window — prevents taskbar from popping up
        self.overrideredirect(True)
        self.attributes('-topmost', True)
        self.transient(parent)

        w, h = 860, 480
        sw = config.SCREEN_MAIN_W
        sh = config.SCREEN_MAIN_H
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.configure(bg="#f4f6f9")
        self.bind("<Destroy>", self._on_destroy)

        self.db = db
        self.scale = scale
        self.camera = camera
        self.selection_provider = selection_provider
        self.state_callback = state_callback
        self.on_open = on_open
        self.on_close = on_close
        self.running = True
        self._is_closed = False
        self._ai_counter = 0
        self._is_predicting = False
        self.current_check = None
        self.current_snapshot = {
            "product": "",
            "weight": 0.0,
            "unit_price": 0.0,
            "total_est": 0.0,
        }
        self.inquiry_items = []
        self.ai = ai_engine
        if self.ai is None:
            raise ValueError("PriceInquiryWindow requires a shared ai_engine instance.")

        self._build_ui()
        self._notify_open()
        self.update_loop()

    def _notify_open(self):
        if callable(self.on_open):
            try:
                self.on_open()
            except Exception as e:
                logger.warning("Price inquiry on_open callback failed: %s", e)

    def _notify_close(self):
        if callable(self.on_close):
            try:
                self.on_close()
            except Exception as e:
                logger.warning("Price inquiry on_close callback failed: %s", e)

    def _on_destroy(self, event):
        if event.widget is not self:
            return
        if self._is_closed:
            return
        self._is_closed = True
        self.running = False
        self._notify_close()

    def _emit_state(self, product, weight, unit_price, total_est, status, is_manual):
        if not callable(self.state_callback):
            return
        payload = {
            "product": str(product or ""),
            "weight": float(weight or 0.0),
            "unit_price": float(unit_price or 0.0),
            "total_est": float(total_est or 0.0),
            "status": str(status or ""),
            "is_manual": bool(is_manual)
        }
        try:
            self.state_callback(payload)
        except Exception as e:
            logger.warning("Price inquiry state callback failed: %s", e)

    def _get_ai_runtime_status(self):
        if hasattr(self.ai, "get_runtime_status") and callable(self.ai.get_runtime_status):
            try:
                return self.ai.get_runtime_status() or {}
            except Exception as e:
                logger.warning("Price inquiry AI status read failed: %s", e)
        return {}

    def _set_ai_status_from_runtime(self):
        status = self._get_ai_runtime_status()
        if not status:
            return False

        feature_ready = bool(status.get("feature_extractor_ready", True))
        if not feature_ready:
            self.current_check = None
            self.lbl_ai_dot.config(fg=config.DANGER_COLOR)
            self.lbl_ai_status.config(text="AI unavailable", fg=config.DANGER_COLOR)
            return True

        profiles_loaded = int(status.get("profiles_loaded") or 0)
        if feature_ready and profiles_loaded <= 0:
            self.current_check = None
            self.lbl_ai_dot.config(fg=config.WARNING_COLOR)
            self.lbl_ai_status.config(text="No AI profiles", fg=config.WARNING_COLOR)
            return True

        return False

    def _get_ai_frames(self):
        if hasattr(self.camera, "get_all_raw_frames") and callable(self.camera.get_all_raw_frames):
            raw_frames = self.camera.get_all_raw_frames()
        else:
            raw_frames = [self.camera.get_raw_frame(i) for i in range(3)]
        return [frame for frame in raw_frames if frame is not None]

    def _build_ui(self):
        # ── Header bar (matches main UI Brand bar) ──────────────────────
        header = tk.Frame(self, bg=config.THEME_COLOR, pady=10, padx=20)
        header.pack(fill=tk.X)

        tk.Label(header, text="AI PRICE INQUIRY", font=("Segoe UI", 18, "bold"),
                 bg=config.THEME_COLOR, fg="white").pack(side=tk.LEFT)

        tk.Button(header, text="✖  CLOSE", font=("Segoe UI", 11, "bold"),
                  bg=config.DANGER_COLOR, fg="white", relief="flat",
                  padx=14, pady=4, activebackground="#e74c3c",
                  command=self.close).pack(side=tk.RIGHT)

        # ── Body ────────────────────────────────────────────────────────
        body = tk.Frame(self, bg="#f4f6f9")
        body.pack(fill=tk.BOTH, expand=True, padx=20, pady=15)

        # Left card — detected product + weight + price
        left_card = tk.Frame(body, bg="white", relief="solid", bd=1)
        left_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

        tk.Label(left_card, text="DETECTED ITEM", font=("Segoe UI", 10, "bold"),
                 bg="white", fg="#7f8c8d").pack(pady=(20, 5))

        self.lbl_prod = tk.Label(left_card, text="Place item on scale…",
                                 font=("Segoe UI", 30, "bold"),
                                 bg="white", fg="#95a5a6", wraplength=400)
        self.lbl_prod.pack(pady=(0, 15))

        divider = tk.Frame(left_card, bg="#ecf0f1", height=2)
        divider.pack(fill=tk.X, padx=30)

        # Weight row
        wt_row = tk.Frame(left_card, bg="white")
        wt_row.pack(fill=tk.X, padx=40, pady=(15, 5))
        tk.Label(wt_row, text="Weight", font=("Segoe UI", 12), bg="white", fg="#7f8c8d").pack(side=tk.LEFT)
        self.lbl_weight = tk.Label(wt_row, text="0.00 kg",
                                   font=("Segoe UI", 22, "bold"), bg="white", fg=config.THEME_COLOR)
        self.lbl_weight.pack(side=tk.RIGHT)

        # Unit price row
        up_row = tk.Frame(left_card, bg="white")
        up_row.pack(fill=tk.X, padx=40, pady=5)
        tk.Label(up_row, text="Unit Price", font=("Segoe UI", 12), bg="white", fg="#7f8c8d").pack(side=tk.LEFT)
        self.lbl_unit = tk.Label(up_row, text="₱ — / kg",
                                 font=("Segoe UI", 22, "bold"), bg="white", fg=config.THEME_COLOR)
        self.lbl_unit.pack(side=tk.RIGHT)

        divider2 = tk.Frame(left_card, bg="#ecf0f1", height=2)
        divider2.pack(fill=tk.X, padx=30, pady=(10, 0))

        # Total row
        tot_row = tk.Frame(left_card, bg="#f8f9fa")
        tot_row.pack(fill=tk.X, padx=0, pady=0, ipady=15)
        tk.Label(tot_row, text="ESTIMATED TOTAL", font=("Segoe UI", 11), bg="#f8f9fa", fg="#7f8c8d").pack()
        self.lbl_total = tk.Label(tot_row, text="₱ 0.00",
                                  font=("Segoe UI", 36, "bold"), bg="#f8f9fa", fg=config.ACCENT_COLOR)
        self.lbl_total.pack()

        # Right card — status / confidence
        right_card = tk.Frame(body, bg="white", relief="solid", bd=1, width=320)
        right_card.pack(side=tk.RIGHT, fill=tk.Y)
        right_card.pack_propagate(False)

        tk.Label(right_card, text="AI STATUS", font=("Segoe UI", 10, "bold"),
                 bg="white", fg="#7f8c8d").pack(pady=(20, 8))

        self.lbl_ai_dot = tk.Label(right_card, text="●", font=("Segoe UI", 36),
                                   bg="white", fg="#bdc3c7")
        self.lbl_ai_dot.pack()

        self.lbl_ai_status = tk.Label(right_card, text="Scanning…",
                                      font=("Segoe UI", 11), bg="white", fg="#7f8c8d",
                                      wraplength=170, justify="center", height=2, anchor="center")
        self.lbl_ai_status.pack(pady=8)

        tk.Frame(right_card, bg="#ecf0f1", height=2).pack(fill=tk.X, padx=14, pady=(4, 8))

        tk.Label(right_card, text="INQUIRY LIST (NO SALE)", font=("Segoe UI", 10, "bold"),
                 bg="white", fg="#7f8c8d").pack(anchor="w", padx=14)

        list_frame = tk.Frame(right_card, bg="white")
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(6, 6))

        cols = ("Item", "Kg", "Total")
        self.inquiry_tree = ttk.Treeview(list_frame, columns=cols, show="headings", height=6)
        self.inquiry_tree.column("Item", width=120, anchor="w")
        self.inquiry_tree.column("Kg", width=55, anchor="center")
        self.inquiry_tree.column("Total", width=85, anchor="e")
        for col in cols:
            self.inquiry_tree.heading(col, text=col)

        sb = ttk.Scrollbar(list_frame, orient="vertical", command=self.inquiry_tree.yview)
        self.inquiry_tree.configure(yscrollcommand=sb.set)
        self.inquiry_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        btn_row = tk.Frame(right_card, bg="white")
        btn_row.pack(fill=tk.X, padx=10, pady=(2, 4))
        ttk.Button(btn_row, text="ADD ITEM", style="Primary.TButton", command=self.add_current_to_inquiry).pack(fill=tk.X)

        btn_row2 = tk.Frame(right_card, bg="white")
        btn_row2.pack(fill=tk.X, padx=10, pady=(0, 4))
        ttk.Button(btn_row2, text="REMOVE SELECTED", style="Secondary.TButton", command=self.remove_selected_inquiry_item).pack(fill=tk.X)

        btn_row3 = tk.Frame(right_card, bg="white")
        btn_row3.pack(fill=tk.X, padx=10, pady=(0, 6))
        ttk.Button(btn_row3, text="CLEAR LIST", style="Danger.TButton", command=self.clear_inquiry_list).pack(fill=tk.X)

        self.lbl_inquiry_total = tk.Label(
            right_card,
            text="Running Total: ₱ 0.00",
            font=("Segoe UI", 12, "bold"),
            bg="white",
            fg=config.ACCENT_COLOR,
            anchor="w"
        )
        self.lbl_inquiry_total.pack(fill=tk.X, padx=14, pady=(0, 12))

    def _get_manual_selection(self):
        if not callable(self.selection_provider):
            return None, 0.0

        try:
            context = self.selection_provider()
        except Exception as e:
            logger.warning("Price inquiry provider error: %s", e)
            return None, 0.0

        if not isinstance(context, dict):
            return None, 0.0

        mode = str(context.get("mode") or "").upper()
        product = context.get("selected_product")
        if mode != "MANUAL" or not product:
            return None, 0.0

        try:
            price = float(context.get("selected_price") or self.db.get_product_price(product))
        except Exception as e:
            logger.warning("Price inquiry price lookup failed for %s: %s", product, e)
            price = 0.0

        return str(product), price

    def _refresh_inquiry_tree(self):
        if not hasattr(self, "inquiry_tree"):
            return
        for item_id in self.inquiry_tree.get_children():
            self.inquiry_tree.delete(item_id)

        running_total = 0.0
        for index, item in enumerate(self.inquiry_items):
            name = str(item.get("product") or "")
            weight = float(item.get("weight") or 0.0)
            total = float(item.get("total") or 0.0)
            running_total += total
            self.inquiry_tree.insert(
                "",
                "end",
                iid=str(index),
                values=(name, f"{weight:.2f}", f"₱ {total:.2f}")
            )

        self.lbl_inquiry_total.config(text=f"Running Total: ₱ {running_total:.2f}")

    def add_current_to_inquiry(self):
        product = str(self.current_snapshot.get("product") or "").strip()
        try:
            weight = round(float(self.current_snapshot.get("weight") or 0.0), 2)
        except (TypeError, ValueError):
            weight = 0.0
        try:
            total_est = round(float(self.current_snapshot.get("total_est") or 0.0), 2)
        except (TypeError, ValueError):
            total_est = 0.0

        if not product or weight < 0.01:
            self.lbl_ai_dot.config(fg=config.WARNING_COLOR)
            self.lbl_ai_status.config(text="Select/detect item with weight first", fg=config.WARNING_COLOR)
            return

        self.inquiry_items.append({
            "product": product,
            "weight": weight,
            "total": total_est,
        })
        self._refresh_inquiry_tree()

    def remove_selected_inquiry_item(self):
        if not hasattr(self, "inquiry_tree"):
            return
        selected = self.inquiry_tree.selection()
        if not selected:
            return

        try:
            idx = int(selected[0])
        except (TypeError, ValueError):
            return

        if 0 <= idx < len(self.inquiry_items):
            del self.inquiry_items[idx]
            self._refresh_inquiry_tree()

    def clear_inquiry_list(self):
        self.inquiry_items = []
        self._refresh_inquiry_tree()

    def _consume_ai_result(self, label, confidence, error_message=None):
        self._is_predicting = False
        if not self.running:
            return

        if error_message:
            logger.warning("Price inquiry AI error: %s", error_message)
            return

        if label and confidence > 0.88 and str(label).lower() not in ["background", "empty", "none"]:
            self.current_check = label
            self.lbl_ai_dot.config(fg=config.SUCCESS_COLOR)
            self.lbl_ai_status.config(
                text=f"{label}\n{confidence*100:.0f}% confidence",
                fg=config.SUCCESS_COLOR
            )

    def update_loop(self):
        if not self.running:
            return

        try:
            weight = self.scale.get_weight()
        except Exception:
            weight = 0.0

        manual_product, manual_price = self._get_manual_selection()
        manual_override = bool(manual_product)

        # Throttle AI to every 5th tick and only run when weight is enough for a valid item.
        if not manual_override and weight >= 0.01:
            self._ai_counter += 1
            if self._ai_counter >= 5 and not self._is_predicting:
                self._ai_counter = 0
                try:
                    if self._set_ai_status_from_runtime():
                        ai_frames = []
                    else:
                        ai_frames = self._get_ai_frames()
                    if ai_frames:
                        self._is_predicting = True

                        def _run_ai():
                            try:
                                label, confidence = self.ai.predict_product(ai_frames)
                                self.after(
                                    0,
                                    lambda: self._consume_ai_result(label, confidence)
                                )
                            except Exception as e:
                                self.after(
                                    0,
                                    lambda err=str(e): self._consume_ai_result(None, 0.0, err)
                                )

                        threading.Thread(target=_run_ai, daemon=True).start()
                except Exception as e:
                    logger.warning("Price inquiry AI error: %s", e)
                    self._is_predicting = False
        elif not manual_override:
            self._ai_counter = 0
            if self.current_check is not None:
                self.current_check = None
            self.lbl_ai_dot.config(fg="#bdc3c7")
            self.lbl_ai_status.config(text="Scanning…", fg="#7f8c8d")

        # Clear if scale is empty
        if not manual_override and weight <= 0.005 and self.current_check is not None:
            self.current_check = None
            self.lbl_ai_dot.config(fg="#bdc3c7")
            self.lbl_ai_status.config(text="Scanning…", fg="#7f8c8d")

        # Refresh display
        calc_weight = round(float(weight or 0.0), 2)
        if manual_override:
            total_est = round(calc_weight * manual_price, 2)
            self.current_snapshot = {
                "product": manual_product,
                "weight": calc_weight,
                "unit_price": manual_price,
                "total_est": total_est,
            }
            self.lbl_prod.config(text=manual_product, fg=config.THEME_COLOR)
            self.lbl_weight.config(text=f"{weight:.2f} kg")
            self.lbl_unit.config(text=f"₱ {manual_price:.2f} / kg")
            self.lbl_total.config(text=f"₱ {total_est:.2f}")
            self.lbl_ai_dot.config(fg="#e67e22")
            self.lbl_ai_status.config(text="Manual selection", fg="#e67e22")
            self._emit_state(
                product=manual_product,
                weight=calc_weight,
                unit_price=manual_price,
                total_est=total_est,
                status="Manual selection",
                is_manual=True
            )
        elif self.current_check:
            price = self.db.get_product_price(self.current_check)
            total_est = round(calc_weight * price, 2)
            self.current_snapshot = {
                "product": self.current_check,
                "weight": calc_weight,
                "unit_price": price,
                "total_est": total_est,
            }
            self.lbl_prod.config(text=self.current_check, fg=config.THEME_COLOR)
            self.lbl_weight.config(text=f"{weight:.2f} kg")
            self.lbl_unit.config(text=f"₱ {price:.2f} / kg")
            self.lbl_total.config(text=f"₱ {total_est:.2f}")
            self._emit_state(
                product=self.current_check,
                weight=calc_weight,
                unit_price=price,
                total_est=total_est,
                status=self.lbl_ai_status.cget("text"),
                is_manual=False
            )
        else:
            self.current_snapshot = {
                "product": "",
                "weight": calc_weight,
                "unit_price": 0.0,
                "total_est": 0.0,
            }
            self.lbl_prod.config(text="Place item on scale…", fg="#95a5a6")
            self.lbl_weight.config(text=f"{weight:.2f} kg")
            self.lbl_unit.config(text="₱ — / kg")
            self.lbl_total.config(text="₱ 0.00")
            self._emit_state(
                product="",
                weight=calc_weight,
                unit_price=0.0,
                total_est=0.0,
                status="Scanning",
                is_manual=False
            )

        self.after(100, self.update_loop)

    def close(self):
        if self._is_closed:
            return
        self._is_closed = True
        self.running = False
        self._notify_close()
        self.destroy()

