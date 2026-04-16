import tkinter as tk
import datetime
from PIL import Image, ImageTk
import os
import config

class CustomerDisplay(tk.Toplevel):
    CART_ITEM_COL_WIDTH = 14
    CART_WEIGHT_COL_WIDTH = 7
    CART_SUBTOTAL_COL_WIDTH = 10
    INQUIRY_ASPECT_RATIO = 860 / 480

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Customer View")
        
        x = config.CUSTOMER_OFFSET_X
        y = config.CUSTOMER_OFFSET_Y
        w = config.SCREEN_CUST_W
        h = config.SCREEN_CUST_H
        
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.configure(bg="#2c3e50")
        self.overrideredirect(True)

        self.is_qr_active = False
        self.is_thanking = False
        self.reset_timer = None
        self._clock_job = None
        self._inquiry_visible = False
        self._inquiry_place = None
        self._inquiry_text_wrap = 220
        self._last_cart_signature = None

        self.setup_ui(w, h)
        # Start in idle mode — selling UI is hidden until a seller logs in
        self.show_idle()


    def setup_ui(self, w, h):
        self._configure_inquiry_geometry(w, h)

        # 1024 * 0.6 = ~614px wide
        self.left_frame = tk.Frame(self, bg="#2c3e50", width=int(w*0.6), height=h)
        self.left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.left_frame.pack_propagate(False) # Force fixed size
        
        # Centering container
        l_container = tk.Frame(self.left_frame, bg="#2c3e50")
        l_container.place(relx=0.5, rely=0.5, anchor="center")
        
        self.lbl_item = tk.Label(l_container, text="Welcome!", font=("Segoe UI", 40, "bold"), fg="#f1c40f", bg="#2c3e50")
        self.lbl_item.pack(pady=10)
        
        self.lbl_weight = tk.Label(l_container, text="0.00 kg", font=("Segoe UI", 65, "bold"), fg="white", bg="#2c3e50")
        self.lbl_weight.pack(pady=10)

        self.lbl_unit_price = tk.Label(l_container, text="", font=("Segoe UI", 20), fg="#bdc3c7", bg="#2c3e50")
        self.lbl_unit_price.pack(pady=5)

        self.lbl_item_total = tk.Label(l_container, text="", font=("Segoe UI", 36, "bold"), fg="#2ecc71", bg="#2c3e50")
        self.lbl_item_total.pack(pady=10)

        # 1024 * 0.4 = ~410px wide
        right_panel_bg = "#253847"
        card_bg = "#304658"
        card_inner_bg = "#3a5165"
        card_border = "#4a657d"
        list_bg = "#243847"
        self.right_frame = tk.Frame(self, bg=right_panel_bg, width=int(w*0.4), height=h)
        self.right_frame.pack(side=tk.RIGHT, fill=tk.BOTH)
        self.right_frame.pack_propagate(False)
        
        r_container = tk.Frame(self.right_frame, bg=right_panel_bg, padx=18, pady=18)
        r_container.pack(fill=tk.BOTH, expand=True)

        totals_card = tk.Frame(
            r_container,
            bg=card_bg,
            padx=16,
            pady=14,
            highlightbackground=card_border,
            highlightthickness=1,
            bd=0,
            relief="flat"
        )
        totals_card.pack(fill=tk.X)

        tk.Label(
            totals_card,
            text="Total Due",
            font=("Segoe UI", 14, "bold"),
            fg="#dce6ee",
            bg=card_bg
        ).pack(anchor="w")
        self.lbl_total = tk.Label(
            totals_card,
            text="₱ 0.00",
            font=("Segoe UI", 44, "bold"),
            fg="#2ecc71",
            bg=card_bg
        )
        self.lbl_total.pack(anchor="w", pady=(4, 10))

        # Est Total (Hidden by default)
        self.est_frame = tk.Frame(
            totals_card,
            bg=card_inner_bg,
            padx=10,
            pady=8,
            highlightbackground=card_border,
            highlightthickness=1
        )
        self.lbl_est_label = tk.Label(self.est_frame, text="With Item:", font=("Segoe UI", 13), fg="#c4d0da", bg=card_inner_bg)
        self.lbl_est_label.pack()
        self.lbl_est_total = tk.Label(self.est_frame, text="₱ 0.00", font=("Segoe UI", 28, "bold"), fg="#ecf0f1", bg=card_inner_bg)
        self.lbl_est_total.pack()

        tk.Label(
            r_container,
            text="Cart Items",
            font=("Segoe UI", 13, "bold"),
            fg="#ecf0f1",
            bg=right_panel_bg
        ).pack(anchor="w", pady=(14, 8))

        cart_card = tk.Frame(
            r_container,
            bg=card_bg,
            padx=14,
            pady=12,
            highlightbackground=card_border,
            highlightthickness=1,
            bd=0,
            relief="flat"
        )
        cart_card.pack(fill=tk.BOTH, expand=True)

        cart_list_area = tk.Frame(
            cart_card,
            bg=list_bg,
            padx=10,
            pady=10,
            highlightbackground=card_border,
            highlightthickness=1,
            bd=0,
            relief="flat"
        )
        cart_list_area.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            cart_list_area,
            text=self._format_cart_header(),
            font=("Consolas", 12, "bold"),
            fg="#b8c6d2",
            bg=list_bg
        ).pack(anchor="w")

        self.cart_listbox = tk.Listbox(
            cart_list_area,
            font=("Consolas", 12),
            bg=list_bg,
            fg="#ecf0f1",
            bd=0,
            highlightthickness=0,
            relief="flat",
            activestyle="none",
            selectbackground=list_bg,
            selectforeground="#ecf0f1"
        )
        self.cart_listbox.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        self._render_cart_lines([])

        self.inquiry_overlay = tk.Frame(
            self,
            bg="#1f2f3d",
            highlightbackground="#4a657d",
            highlightthickness=1,
            bd=0,
            relief="flat"
        )

        inquiry_header = tk.Frame(self.inquiry_overlay, bg="#2f4658", pady=6, padx=10)
        inquiry_header.pack(fill=tk.X)
        tk.Label(
            inquiry_header,
            text="Price Check",
            font=("Segoe UI", 12, "bold"),
            fg="#ecf0f1",
            bg="#2f4658"
        ).pack(side=tk.LEFT)

        self.inquiry_status_lbl = tk.Label(
            inquiry_header,
            text="Scanning",
            font=("Segoe UI", 10),
            fg="#bdc3c7",
            bg="#2f4658",
            wraplength=max(120, self._inquiry_text_wrap // 2)
        )
        self.inquiry_status_lbl.pack(side=tk.RIGHT)

        inquiry_body = tk.Frame(self.inquiry_overlay, bg="#1f2f3d", padx=12, pady=10)
        inquiry_body.pack(fill=tk.BOTH, expand=True)

        self.inquiry_item_lbl = tk.Label(
            inquiry_body,
            text="Place item on scale",
            font=("Segoe UI", 14, "bold"),
            fg="#f1c40f",
            bg="#1f2f3d",
            anchor="w",
            justify="left",
            wraplength=self._inquiry_text_wrap
        )
        self.inquiry_item_lbl.pack(fill=tk.X)

        self.inquiry_weight_lbl = tk.Label(
            inquiry_body,
            text="0.00 kg",
            font=("Segoe UI", 11),
            fg="#ecf0f1",
            bg="#1f2f3d",
            anchor="w"
        )
        self.inquiry_weight_lbl.pack(fill=tk.X, pady=(6, 0))

        self.inquiry_unit_lbl = tk.Label(
            inquiry_body,
            text="₱ 0.00 / kg",
            font=("Segoe UI", 11),
            fg="#bdc3c7",
            bg="#1f2f3d",
            anchor="w"
        )
        self.inquiry_unit_lbl.pack(fill=tk.X, pady=(2, 0))

        self.inquiry_total_lbl = tk.Label(
            inquiry_body,
            text="Est. ₱ 0.00",
            font=("Segoe UI", 20, "bold"),
            fg="#2ecc71",
            bg="#1f2f3d",
            anchor="w"
        )
        self.inquiry_total_lbl.pack(fill=tk.X, pady=(8, 0))

        self.qr_frame = tk.Frame(self, bg="#1a252f")

        # GCash header
        gcash_header = tk.Frame(self.qr_frame, bg="#00a651", pady=16)
        gcash_header.pack(fill=tk.X)
        tk.Label(gcash_header, text="💚  GCash Payment",
                 font=("Segoe UI", 22, "bold"), bg="#00a651", fg="white").pack()

        # Amount label (updated dynamically in show_qr)
        self.qr_amount_lbl = tk.Label(self.qr_frame, text="",
                                      font=("Segoe UI", 36, "bold"),
                                      bg="#1a252f", fg="#f1c40f")
        self.qr_amount_lbl.pack(pady=(20, 4))

        tk.Label(self.qr_frame, text="Amount to Pay",
                 font=("Segoe UI", 13), bg="#1a252f", fg="#95a5a6").pack()

        # QR code in a white card
        qr_card = tk.Frame(self.qr_frame, bg="white", padx=12, pady=12,
                           relief="flat")
        qr_card.pack(pady=20)
        self.qr_img_lbl = tk.Label(qr_card, bg="white",
                                   text="QR Code\nNot Found", fg="#c0392b",
                                   font=("Segoe UI", 14))
        self.qr_img_lbl.pack()

        # Scan instruction
        tk.Label(self.qr_frame, text="📱  Scan QR Code to Pay",
                 font=("Segoe UI", 17, "bold"), bg="#1a252f", fg="white").pack(pady=(0, 10))

        self.ty_frame = tk.Frame(self, bg="#27ae60")

        # Center container fills the whole overlay
        ty_container = tk.Frame(self.ty_frame, bg="#27ae60")
        ty_container.place(relx=0.5, rely=0.5, anchor="center")

        # Large checkmark
        tk.Label(ty_container, text="✔", font=("Segoe UI", 72, "bold"),
                 fg="white", bg="#27ae60").pack()

        # Main heading
        tk.Label(ty_container, text="Thank You!",
                 font=("Segoe UI", 58, "bold"), fg="white", bg="#27ae60").pack()

        # Thin divider
        div = tk.Frame(ty_container, bg="white", height=3)
        div.pack(fill=tk.X, padx=40, pady=(10, 14))

        # Sub-text
        tk.Label(ty_container, text="Please Come Again  🌿",
                 font=("Segoe UI", 26), fg="#d5f5e3", bg="#27ae60").pack()

        tk.Label(ty_container, text="Have a wonderful day!",
                 font=("Segoe UI", 16), fg="#a9dfbf", bg="#27ae60").pack(pady=(6, 0))

        self.idle_frame = tk.Frame(self, bg=config.THEME_COLOR)

        idle_body = tk.Frame(self.idle_frame, bg=config.THEME_COLOR)
        idle_body.place(relx=0.5, rely=0.5, anchor="center")

        # Store icon/emoji
        tk.Label(idle_body, text="🌿", font=("Segoe UI", 64),
                 bg=config.THEME_COLOR, fg="#f1c40f").pack()

        # Store name
        tk.Label(idle_body, text="SmartPOS",
                 font=("Segoe UI", 42, "bold"), bg=config.THEME_COLOR, fg="white").pack(pady=(4, 2))

        tk.Label(idle_body, text="Fresh Produce Market",
                 font=("Segoe UI", 18), bg=config.THEME_COLOR, fg="#95a5a6").pack()

        # Divider
        tk.Frame(idle_body, bg=config.ACCENT_COLOR, height=3).pack(fill=tk.X, pady=18, padx=20)

        tk.Label(idle_body, text="Welcome!  Please wait for the seller.",
                 font=("Segoe UI", 15), bg=config.THEME_COLOR, fg="#bdc3c7").pack()

        # Live clock
        self.idle_clock = tk.Label(idle_body, text="",
                                   font=("Segoe UI", 22, "bold"),
                                   bg=config.THEME_COLOR, fg="#f1c40f")
        self.idle_clock.pack(pady=(18, 0))

    def _tick_clock(self):
        now = datetime.datetime.now().strftime("%I:%M %p  |  %A, %B %d")
        try:
            self.idle_clock.config(text=now)
        except Exception:
            return
        self._clock_job = self.after(30000, self._tick_clock)

    def show_idle(self):
        self.hide_price_inquiry_overlay()
        self.hide_qr()
        self.stop_thank_you()
        if self._clock_job:
            self.after_cancel(self._clock_job)
            self._clock_job = None
        self.idle_frame.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.idle_frame.lift()
        self._tick_clock()

    def show_selling(self):
        self.hide_price_inquiry_overlay()
        self.hide_qr()
        self.stop_thank_you()
        self.idle_frame.place_forget()
        if self._clock_job:
            self.after_cancel(self._clock_job)
            self._clock_job = None

    def _format_cart_header(self):
        return (
            f"{'Item':<{self.CART_ITEM_COL_WIDTH}} "
            f"{'Kg':>{self.CART_WEIGHT_COL_WIDTH}} "
            f"{'Subtotal':>{self.CART_SUBTOTAL_COL_WIDTH}}"
        )

    def _format_cart_row(self, name, weight, subtotal):
        short_name = name[:self.CART_ITEM_COL_WIDTH]
        subtotal_text = f"₱{subtotal:.2f}"
        return (
            f"{short_name:<{self.CART_ITEM_COL_WIDTH}} "
            f"{weight:>{self.CART_WEIGHT_COL_WIDTH}.2f} "
            f"{subtotal_text:>{self.CART_SUBTOTAL_COL_WIDTH}}"
        )

    def _render_cart_lines(self, cart_items):
        self.cart_listbox.delete(0, tk.END)
        if not cart_items:
            self.cart_listbox.insert(tk.END, "No items yet")
            self.cart_listbox.itemconfig(0, fg="#95a5a6")
            return

        for item in cart_items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "")
            try:
                weight = float(item.get("weight") or 0.0)
                subtotal = float(item.get("total") or 0.0)
            except (TypeError, ValueError):
                continue

            line = self._format_cart_row(name, weight, subtotal)
            self.cart_listbox.insert(tk.END, line)

        if self.cart_listbox.size() == 0:
            self.cart_listbox.insert(tk.END, "No items yet")
            self.cart_listbox.itemconfig(0, fg="#95a5a6")

    def _build_cart_signature(self, cart_items):
        signature = []
        for item in (cart_items or []):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "")
            try:
                weight = round(float(item.get("weight") or 0.0), 2)
            except (TypeError, ValueError):
                weight = 0.0
            try:
                subtotal = round(float(item.get("total") or 0.0), 2)
            except (TypeError, ValueError):
                subtotal = 0.0
            signature.append((name, weight, subtotal))
        return tuple(signature)

    def update_view(self, item_name, weight, cart_total, price_per_kg=0.0, cart_items=None):
        if self.is_qr_active: return 
        
        if self.is_thanking:
            new_activity_detected = (price_per_kg > 0) or (cart_total > 0)
            if new_activity_detected: self.stop_thank_you()
            else: return 

        if len(item_name) > 18: item_name = item_name[:18] + "..."
        calc_weight = round(float(weight or 0.0), 2)
        self.lbl_item.config(text=item_name)
        self.lbl_weight.config(text=f"{weight:.2f} kg")
        
        if price_per_kg > 0 and calc_weight >= 0.01:
            item_subtotal = round(calc_weight * price_per_kg, 2)
            projected_total = round(float(cart_total or 0.0) + item_subtotal, 2)
            
            self.lbl_unit_price.config(text=f"@ ₱ {price_per_kg:.2f} / kg")
            self.lbl_item_total.config(text=f"₱ {item_subtotal:.2f}")
            
            self.est_frame.pack(fill=tk.X, pady=(0, 2)) # Show estimated
            self.lbl_est_total.config(text=f"₱ {projected_total:.2f}")
        else:
            self.lbl_unit_price.config(text="")
            self.lbl_item_total.config(text="")
            self.est_frame.pack_forget() # Hide estimated

        self.lbl_total.config(text=f"₱ {cart_total:.2f}")
        current_signature = self._build_cart_signature(cart_items or [])
        if current_signature != self._last_cart_signature:
            self._render_cart_lines(cart_items or [])
            self._last_cart_signature = current_signature

    def show_price_inquiry_overlay(self):
        if self.is_qr_active or self.is_thanking:
            return
        self._inquiry_visible = True
        self.inquiry_overlay.place(**self._inquiry_place)
        self.inquiry_overlay.lift()

    def hide_price_inquiry_overlay(self):
        self._inquiry_visible = False
        self.inquiry_overlay.place_forget()

    def update_price_inquiry_overlay(self, state):
        if not isinstance(state, dict):
            return

        if not self._inquiry_visible and not self.is_qr_active and not self.is_thanking:
            self.show_price_inquiry_overlay()

        product = str(state.get("product") or "").strip()
        status = str(state.get("status") or "Scanning")
        try:
            weight = float(state.get("weight") or 0.0)
        except (TypeError, ValueError):
            weight = 0.0
        try:
            unit_price = float(state.get("unit_price") or 0.0)
        except (TypeError, ValueError):
            unit_price = 0.0
        try:
            total_est = float(state.get("total_est") or 0.0)
        except (TypeError, ValueError):
            total_est = 0.0

        self.inquiry_status_lbl.config(text=status if status else "Scanning")
        self.inquiry_item_lbl.config(text=product if product else "Place item on scale")
        self.inquiry_weight_lbl.config(text=f"{weight:.2f} kg")
        self.inquiry_unit_lbl.config(text=f"₱ {unit_price:.2f} / kg" if unit_price > 0 else "₱ 0.00 / kg")
        self.inquiry_total_lbl.config(text=f"Est. ₱ {total_est:.2f}")

    def show_qr(self, amount=0.0):
        self.is_qr_active = True
        if self._inquiry_visible:
            self.inquiry_overlay.place_forget()
        if amount > 0:
            self.qr_amount_lbl.config(text=f"₱ {amount:.2f}")
        else:
            self.qr_amount_lbl.config(text="")
        found_image = None
        for filename in ["qr_code.png", "qr_code.jpg", "qr_code.jpeg"]:
            path = os.path.join(config.ASSETS_DIR, filename)
            if os.path.exists(path):
                found_image = path
                break
        
        if found_image:
            try:
                load = Image.open(found_image).resize((340, 340))
                render = ImageTk.PhotoImage(load)
                self.qr_img_lbl.config(image=render, text="")
                self.qr_img_lbl.image = render
            except Exception:
                pass
        self.qr_frame.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.qr_frame.lift()

    def hide_qr(self):
        self.qr_frame.place_forget()
        self.is_qr_active = False
        if self._inquiry_visible:
            self.inquiry_overlay.place(**self._inquiry_place)
            self.inquiry_overlay.lift()

    def show_thank_you(self):
        self.is_thanking = True
        self.hide_price_inquiry_overlay()
        self.hide_qr()
        self.ty_frame.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.ty_frame.lift()
        if self.reset_timer: self.after_cancel(self.reset_timer)
        self.reset_timer = self.after(5000, self.show_welcome)

    def stop_thank_you(self):
        self.is_thanking = False
        self.ty_frame.place_forget()
        if self.reset_timer:
            self.after_cancel(self.reset_timer)
            self.reset_timer = None

    def show_welcome(self):
        self.stop_thank_you()
        self.hide_price_inquiry_overlay()
        self.lbl_item.config(text="Welcome!")
        self.lbl_weight.config(text="0.00 kg")
        self.lbl_unit_price.config(text="")
        self.lbl_item_total.config(text="")
        self.lbl_total.config(text="₱ 0.00")
        self.est_frame.pack_forget()
        self._render_cart_lines([])

    def _configure_inquiry_geometry(self, screen_w, screen_h):
        width_px = int(screen_w * 0.43)
        width_px = max(340, min(width_px, int(screen_w * 0.52)))

        height_px = int(width_px / self.INQUIRY_ASPECT_RATIO)
        height_px = max(190, min(height_px, int(screen_h * 0.44)))

        # Keep a seller-like panel proportion while respecting smaller customer display space.
        width_px = int(height_px * self.INQUIRY_ASPECT_RATIO)

        x_px = max(0, (screen_w - width_px) // 2)
        y_px = max(0, (screen_h - height_px) // 2)

        self._inquiry_place = {
            "x": x_px,
            "y": y_px,
            "width": width_px,
            "height": height_px
        }
        self._inquiry_text_wrap = max(180, width_px - 32)

