import tkinter as tk
from tkinter import ttk, filedialog
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import cv2
import os
import json
import threading
from urllib import error, request
from urllib.parse import quote
from PIL import Image, ImageTk
import logging
import config
from ui.virtual_keyboard import VirtualKeyboard

logger = logging.getLogger(__name__)

class AdminDashboard:
    def __init__(self, root, db, camera, logout_cb, ai_engine=None, scale=None):
        self.root = root
        self.db = db
        self.camera = camera
        self.scale = scale
        self.logout_cb = logout_cb
        self.running = True 
        self._train_task_in_progress = False
        self.seller_editor_popup = None
        self.seller_editor_keyboard = None
        self.admin_pin_popup = None
        self.admin_pin_keyboard = None
        self._settings_active_canvas = None
        self._settings_scroll_bound = False
        self._seller_popup_hint_text = (
            "Tap Seller Name or Seller PIN, or use Add Seller/Update Seller, to open the seller editor popup above the keyboard."
        )
        self._admin_login_pin_label = "Admin Dashboard/Login PIN"
        self._admin_pin_popup_hint_text = (
            "This is the same 4-digit PIN used for Admin Dashboard login and Settings unlock (default: 1234)."
        )
        self._admin_pin_status_default_text = (
            "Tap any inline PIN field to auto-open the compact popup above the keyboard, "
            "or use the inline form with a physical keyboard. "
            "For security, your current PIN is always required."
        )
        
        # Reuse app-level AI engine to avoid repeated model loads.
        self.ai = ai_engine
        if self.ai is None:
            raise ValueError("AdminDashboard requires a shared ai_engine instance.")
        
        self.root.configure(bg="#f4f6f9")
        self.setup_ui()

    def attach_training_keyboard(self, parent, entry_widget):
        def on_click(event):
            if not hasattr(self, 'shared_vk') or not self.shared_vk.winfo_exists():
                self.shared_vk = VirtualKeyboard(self.root)
            self.shared_vk.deiconify() 
            self.shared_vk.set_target(entry_widget)
            entry_widget.focus_set()
        entry_widget.bind("<Button-1>", on_click)

    def _ensure_settings_scroll_binding(self):
        if self._settings_scroll_bound:
            return
        self.root.bind_all("<MouseWheel>", self._on_settings_mousewheel, add="+")
        self._settings_scroll_bound = True

    def _set_settings_active_canvas(self, canvas):
        if canvas is not None and canvas.winfo_exists():
            self._settings_active_canvas = canvas

    def _clear_settings_active_canvas(self, canvas):
        if self._settings_active_canvas is canvas:
            self._settings_active_canvas = None

    def _on_settings_mousewheel(self, event):
        canvas = self._settings_active_canvas
        if not canvas or not canvas.winfo_exists():
            return
        try:
            current_tab = self.notebook.nametowidget(self.notebook.select())
            if current_tab is not self.tab_settings:
                return
        except Exception:
            return

        if not getattr(event, "delta", 0):
            return
        step = int(-1 * (event.delta / 120))
        if step == 0:
            return
        canvas.yview_scroll(step, "units")
        return "break"

    def _create_settings_scrollable_tab(self, tab_parent):
        container = tk.Frame(tab_parent, bg="#f8f9fa")
        container.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(container, bg="#f8f9fa", highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        content = tk.Frame(canvas, bg="#f8f9fa")

        window_id = canvas.create_window((0, 0), window=content, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        def on_content_configure(_event):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def on_canvas_configure(event):
            canvas.itemconfigure(window_id, width=event.width)

        content.bind("<Configure>", on_content_configure)
        canvas.bind("<Configure>", on_canvas_configure)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        for widget in (canvas, content):
            widget.bind("<Enter>", lambda _e, c=canvas: self._set_settings_active_canvas(c))
            widget.bind("<Leave>", lambda _e, c=canvas: self._clear_settings_active_canvas(c))

        self._ensure_settings_scroll_binding()
        return content, canvas

    def _on_settings_subtab_changed(self, _event=None):
        if not hasattr(self, "settings_subtabs") or not self.settings_subtabs.winfo_exists():
            return
        selected = self.settings_subtabs.select()
        if not selected:
            return
        selected_tab = self.settings_subtabs.nametowidget(selected)
        if getattr(self, "settings_seller_tab", None) is selected_tab:
            self._set_settings_active_canvas(getattr(self, "settings_seller_canvas", None))
        elif getattr(self, "settings_admin_tab", None) is selected_tab:
            self._set_settings_active_canvas(getattr(self, "settings_admin_canvas", None))
        elif getattr(self, "settings_scale_tab", None) is selected_tab:
            self._set_settings_active_canvas(getattr(self, "settings_scale_canvas", None))

    def setup_ui(self):
        header = ttk.Frame(self.root, style="Brand.TFrame", padding="20 10")
        header.pack(fill=tk.X)
        ttk.Label(header, text="ADMIN DASHBOARD", style="Brand.TLabel").pack(side=tk.LEFT)
        ttk.Button(header, text="LOGOUT", command=self.logout, style="Danger.TButton").pack(side=tk.RIGHT)
        
        container = ttk.Frame(self.root, style="Main.TFrame", padding=20)
        container.pack(fill=tk.BOTH, expand=True)
        self.notebook = ttk.Notebook(container)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)
        
        self.tab_inv = ttk.Frame(self.notebook, style="Main.TFrame", padding=20)
        self.notebook.add(self.tab_inv, text="  Inventory  ")
        self.tab_train = ttk.Frame(self.notebook, style="Card.TFrame", padding=20)
        self.notebook.add(self.tab_train, text="  Training  ")
        self.tab_history = ttk.Frame(self.notebook, style="Card.TFrame", padding=20)
        self.notebook.add(self.tab_history, text="  History  ")
        self.tab_report = ttk.Frame(self.notebook, style="Card.TFrame", padding=20)
        self.notebook.add(self.tab_report, text="  Reports  ")
        self.tab_settings = ttk.Frame(self.notebook, style="Card.TFrame", padding=20)
        self.notebook.add(self.tab_settings, text="  Settings  ")
        
        self.build_inventory_tab()
        self.build_training_tab()
        self.build_history_tab()
        self.build_reports_tab()
        self.build_settings_tab()

    def _on_tab_changed(self, event=None):
        if hasattr(self, 'shared_vk') and self.shared_vk.winfo_exists():
            self.shared_vk.withdraw()
        try:
            current_tab = self.notebook.nametowidget(self.notebook.select())
            if current_tab is not self.tab_settings:
                self._settings_active_canvas = None
        except Exception:
            self._settings_active_canvas = None

    def logout(self):
        self.running = False
        self.logout_cb()

    def show_custom_error(self, parent, title, message):
        err_win = tk.Toplevel(parent)
        err_win.configure(bg="white", highlightbackground="#c0392b", highlightthickness=2)
        err_win.transient(parent)
        err_win.overrideredirect(True)
        err_win.attributes('-topmost', True)
        
        parent.update_idletasks()
        cw, ch = 300, 150
        cx = parent.winfo_x() + (parent.winfo_width() - cw) // 2
        cy = parent.winfo_y() + (parent.winfo_height() - ch) // 2
        err_win.geometry(f"{cw}x{ch}+{cx}+{cy}")
        
        ttk.Label(err_win, text=title, font=("Segoe UI", 12, "bold"), background="white", foreground="#c0392b").pack(pady=(15, 5))
        ttk.Label(err_win, text=message, background="white", wraplength=280).pack(pady=5)
        ttk.Button(err_win, text="OK", command=err_win.destroy, style="Danger.TButton").pack(pady=15)
        
        err_win.update_idletasks()
        err_win.grab_set()

    def build_inventory_tab(self):
        panel = ttk.Frame(self.tab_inv, style="Main.TFrame")
        panel.pack(fill=tk.BOTH, expand=True)
        
        action_bar = tk.Frame(panel, bg="#f4f6f9")
        action_bar.pack(fill=tk.X, pady=(0, 10))
        ttk.Button(action_bar, text="+ ADD NEW PRODUCT", command=self.on_add_product, style="Primary.TButton").pack(side=tk.RIGHT)
        
        header_frame = tk.Frame(panel, bg="#f4f6f9")
        header_frame.pack(fill=tk.X, pady=(0, 10))
        headers = ["Product Name", "Price per kg", "Stock"]
        header_frame.columnconfigure((0, 1, 2), weight=1, uniform="header_col")
        for i, text in enumerate(headers):
            lbl = ttk.Label(header_frame, text=text, style="SubHeader.TLabel")
            lbl.grid(row=0, column=i, sticky="w", padx=10)
            
        container = tk.Frame(panel, bg="white", relief="solid", bd=1)
        container.pack(fill=tk.BOTH, expand=True)
        canvas = tk.Canvas(container, bg="white", highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        self.scroll_frame = tk.Frame(canvas, bg="white")
        
        self.scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.scroll_frame, anchor="nw", width=config.SCREEN_MAIN_W - 100)
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.refresh_inventory()

    def refresh_inventory(self):
        for widget in self.scroll_frame.winfo_children(): widget.destroy()
        self.scroll_frame.columnconfigure((0, 1, 2), weight=1, uniform="prod_grid")
        
        products = self.db.get_all_products()
        for i, prod in enumerate(products):
            name, price, stock = prod
            action_cmd = lambda n=name, p=price, s=stock: self.on_product_click(n, p, s)
            params = {"bg": "#ecf0f1", "fg": "#2c3e50", "relief": "flat", "height": 3, "command": action_cmd}
            
            tk.Button(self.scroll_frame, text=name, font=("Segoe UI", 11, "bold"), **params).grid(row=i, column=0, sticky="nsew", padx=5, pady=5)
            tk.Button(self.scroll_frame, text=f"₱ {price:.2f}", font=("Segoe UI", 11), **params).grid(row=i, column=1, sticky="nsew", padx=5, pady=5)
            tk.Button(self.scroll_frame, text=f"{stock:.2f} kg", font=("Segoe UI", 11), **params).grid(row=i, column=2, sticky="nsew", padx=5, pady=5)

    def on_product_click(self, name, price, stock):
        dialog = tk.Toplevel(self.root)
        dialog.configure(bg="white", highlightbackground="#bdc3c7", highlightthickness=2)
        dialog.transient(self.root)
        dialog.overrideredirect(True)
        dialog.withdraw()   # hide until geometry is set — prevents position flash
        
        vk = VirtualKeyboard(dialog)

        def close_dialog():
            dialog.grab_release()
            dialog.destroy()

        top_bar = tk.Frame(dialog, bg="white")
        top_bar.pack(fill=tk.X, padx=10, pady=(10, 0))
        ttk.Label(top_bar, text=f"Manage: {name}", font=("Segoe UI", 12, "bold"), background="white").pack(side=tk.LEFT)
        close_btn = tk.Button(top_bar, text="✖", font=("Segoe UI", 12), bg="#e74c3c", fg="white", relief="flat", command=close_dialog, width=3)
        close_btn.pack(side=tk.RIGHT)
        
        frame_inputs = tk.Frame(dialog, bg="white")
        frame_inputs.pack(pady=5)
        
        ttk.Label(frame_inputs, text="Price (₱):", background="white").grid(row=0, column=0, padx=5, pady=5, sticky="e")
        ent_price = ttk.Entry(frame_inputs, font=("Segoe UI", 11))
        ent_price.insert(0, str(price))
        ent_price.grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(frame_inputs, text="Stock (kg):", background="white").grid(row=1, column=0, padx=5, pady=5, sticky="e")
        ent_stock = ttk.Entry(frame_inputs, font=("Segoe UI", 11))
        ent_stock.insert(0, str(stock))
        ent_stock.grid(row=1, column=1, padx=5, pady=5)

        def focus_price(e=None):
            vk.deiconify() 
            vk.set_target(ent_price)
            ent_price.focus_set()

        def focus_stock(e=None):
            vk.deiconify() 
            vk.set_target(ent_stock)
            ent_stock.focus_set()

        ent_price.bind("<Button-1>", focus_price)
        ent_stock.bind("<Button-1>", focus_stock)
        focus_price()

        def save_changes():
            try:
                new_price = float(ent_price.get())
                new_stock = float(ent_stock.get())
                self.db.update_product(name, new_price, new_stock)
                self.refresh_inventory()
                close_dialog()
            except ValueError:
                self.show_custom_error(dialog, "Input Error", "Price and Stock must be valid numbers.")

        def delete_item():
            confirm_win = tk.Toplevel(dialog)
            confirm_win.configure(bg="white", highlightbackground="#e74c3c", highlightthickness=2)
            confirm_win.transient(dialog)
            confirm_win.overrideredirect(True)
            confirm_win.attributes('-topmost', True)
            
            cw, ch = 300, 150
            dialog.update_idletasks()
            cx = dialog.winfo_x() + (dialog.winfo_width() - cw) // 2
            cy = dialog.winfo_y() + (dialog.winfo_height() - ch) // 2
            confirm_win.geometry(f"{cw}x{ch}+{cx}+{cy}")

            ttk.Label(confirm_win, text="Confirm Deletion", font=("Segoe UI", 12, "bold"), background="white", foreground="#c0392b").pack(pady=(15, 5))
            ttk.Label(confirm_win, text=f"Delete {name} permanently?", background="white").pack(pady=5)

            def on_confirm():
                self.db.delete_product(name)
                self.refresh_inventory()
                confirm_win.destroy()
                close_dialog()

            def on_cancel():
                confirm_win.destroy()

            btn_f = tk.Frame(confirm_win, bg="white")
            btn_f.pack(pady=15)
            ttk.Button(btn_f, text="Delete", command=on_confirm, style="Danger.TButton").pack(side=tk.LEFT, padx=10)
            ttk.Button(btn_f, text="Cancel", command=on_cancel, style="Secondary.TButton").pack(side=tk.LEFT, padx=10)
            
            confirm_win.update_idletasks()
            confirm_win.grab_set() 

        frame_btns = tk.Frame(dialog, bg="white")
        frame_btns.pack(pady=15)
        ttk.Button(frame_btns, text="Save", command=save_changes, style="Primary.TButton").pack(side=tk.LEFT, padx=5)
        ttk.Button(frame_btns, text="Delete", command=delete_item, style="Danger.TButton").pack(side=tk.LEFT, padx=5)
        ttk.Button(frame_btns, text="Cancel", command=close_dialog, style="Secondary.TButton").pack(side=tk.LEFT, padx=5)

        # Apply dynamic geometry after packing widgets
        dialog.update_idletasks()
        sw = config.SCREEN_MAIN_W
        sh = config.SCREEN_MAIN_H
        dw = 400
        dh = dialog.winfo_reqheight()
        kh = 300
        padding = 20
        dx = (sw - dw) // 2
        dy = sh - kh - dh - padding
        dialog.geometry(f"{dw}x{dh}+{dx}+{dy}")
        dialog.deiconify()   # now show in correct position
        dialog.grab_set()

    def on_add_product(self):
        dialog = tk.Toplevel(self.root)
        dialog.configure(bg="white", highlightbackground="#bdc3c7", highlightthickness=2)
        dialog.transient(self.root)
        dialog.overrideredirect(True)
        dialog.withdraw()   # hide until geometry is set — prevents position flash
        
        vk = VirtualKeyboard(dialog)

        def close_dialog():
            dialog.grab_release()
            dialog.destroy()

        def attempt_close():
            if ent_name.get().strip() or ent_price.get().strip() or ent_stock.get().strip():
                confirm_win = tk.Toplevel(dialog)
                confirm_win.configure(bg="white", highlightbackground="#e74c3c", highlightthickness=2)
                confirm_win.transient(dialog)
                confirm_win.overrideredirect(True)
                confirm_win.attributes('-topmost', True)
                
                cw, ch = 300, 150
                dialog.update_idletasks()
                cx = dialog.winfo_x() + (dialog.winfo_width() - cw) // 2
                cy = dialog.winfo_y() + (dialog.winfo_height() - ch) // 2
                confirm_win.geometry(f"{cw}x{ch}+{cx}+{cy}")

                ttk.Label(confirm_win, text="Unsaved Data", font=("Segoe UI", 12, "bold"), background="white", foreground="#c0392b").pack(pady=(15, 5))
                ttk.Label(confirm_win, text="Discard entered details?", background="white").pack(pady=5)

                def on_confirm():
                    confirm_win.destroy()
                    close_dialog()

                def on_cancel():
                    confirm_win.destroy()

                btn_f = tk.Frame(confirm_win, bg="white")
                btn_f.pack(pady=15)
                ttk.Button(btn_f, text="Discard", command=on_confirm, style="Danger.TButton").pack(side=tk.LEFT, padx=10)
                ttk.Button(btn_f, text="Cancel", command=on_cancel, style="Secondary.TButton").pack(side=tk.LEFT, padx=10)
                
                confirm_win.update_idletasks()
                confirm_win.grab_set()
            else:
                close_dialog()

        top_bar = tk.Frame(dialog, bg="white")
        top_bar.pack(fill=tk.X, padx=10, pady=(10, 0))
        ttk.Label(top_bar, text="Add New Product", font=("Segoe UI", 12, "bold"), background="white").pack(side=tk.LEFT)
        close_btn = tk.Button(top_bar, text="✖", font=("Segoe UI", 12), bg="#e74c3c", fg="white", relief="flat", command=attempt_close, width=3)
        close_btn.pack(side=tk.RIGHT)
        
        spacer = tk.Frame(dialog, bg="white", height=10)
        spacer.pack(fill=tk.X)
        
        frame_inputs = tk.Frame(dialog, bg="white")
        frame_inputs.pack(pady=5)
        
        ttk.Label(frame_inputs, text="Name:", background="white").grid(row=0, column=0, padx=5, pady=5, sticky="e")
        ent_name = ttk.Entry(frame_inputs, font=("Segoe UI", 11))
        ent_name.grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(frame_inputs, text="Price (₱):", background="white").grid(row=1, column=0, padx=5, pady=5, sticky="e")
        ent_price = ttk.Entry(frame_inputs, font=("Segoe UI", 11))
        ent_price.grid(row=1, column=1, padx=5, pady=5)

        ttk.Label(frame_inputs, text="Stock (kg):", background="white").grid(row=2, column=0, padx=5, pady=5, sticky="e")
        ent_stock = ttk.Entry(frame_inputs, font=("Segoe UI", 11))
        ent_stock.grid(row=2, column=1, padx=5, pady=5)

        def focus_field(entry_widget):
            vk.deiconify() 
            vk.set_target(entry_widget)
            entry_widget.focus_set()

        ent_name.bind("<Button-1>", lambda e: focus_field(ent_name))
        ent_price.bind("<Button-1>", lambda e: focus_field(ent_price))
        ent_stock.bind("<Button-1>", lambda e: focus_field(ent_stock))
        focus_field(ent_name) 

        def save_new():
            name = ent_name.get().strip()
            if not name:
                self.show_custom_error(dialog, "Error", "Product name cannot be empty.")
                return
            try:
                price = float(ent_price.get())
                stock = float(ent_stock.get())
                if self.db.add_product(name, price, stock):
                    self.refresh_inventory()
                    close_dialog()
                else:
                    self.show_custom_error(dialog, "Database Error", "Product already exists or could not be added.")
            except ValueError:
                self.show_custom_error(dialog, "Input Error", "Price and Stock must be valid numbers.")

        frame_btns = tk.Frame(dialog, bg="white")
        frame_btns.pack(pady=15)
        ttk.Button(frame_btns, text="Save", command=save_new, style="Primary.TButton").pack(side=tk.LEFT, padx=5)
        ttk.Button(frame_btns, text="Cancel", command=attempt_close, style="Secondary.TButton").pack(side=tk.LEFT, padx=5)

        # Apply dynamic geometry after packing widgets
        dialog.update_idletasks()
        sw = config.SCREEN_MAIN_W
        sh = config.SCREEN_MAIN_H
        dw = 400
        dh = dialog.winfo_reqheight()
        kh = 300
        padding = 20
        dx = (sw - dw) // 2
        dy = sh - kh - dh - padding
        dialog.geometry(f"{dw}x{dh}+{dx}+{dy}")
        dialog.deiconify()   # now show in correct position
        dialog.grab_set()

    def build_training_tab(self):
        # ── Page header ─────────────────────────────────────────────────
        header = ttk.Frame(self.tab_train, style="Brand.TFrame", padding=(20, 12))
        header.pack(fill=tk.X)
        ttk.Label(header, text="AI Training — Capture or Upload Dataset Images",
                  style="Brand.TLabel").pack(side=tk.LEFT)

        # ── Two-column body ──────────────────────────────────────────────
        body = tk.Frame(self.tab_train, bg="#f4f6f9")
        body.pack(fill=tk.BOTH, expand=True, padx=20, pady=15)

        # ── LEFT: camera preview card ────────────────────────────────────
        cam_card = tk.Frame(body, bg="white", relief="solid", bd=1)
        cam_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

        tk.Label(cam_card, text="LIVE CAMERA PREVIEW", font=("Segoe UI", 10, "bold"),
                 bg="white", fg="#7f8c8d").pack(pady=(14, 6))

        cam_border = tk.Frame(cam_card, bg="#2c3e50", padx=4, pady=4)
        cam_border.pack(expand=True)

        self.train_cam_lbl = tk.Label(cam_border, bg="#2c3e50", width=480, height=360)
        self.train_cam_lbl.pack()

        tk.Label(cam_card, text="Position the product clearly in frame before capturing.",
                 font=("Segoe UI", 9), bg="white", fg="#95a5a6").pack(pady=(6, 14))

        # ── RIGHT: controls card ─────────────────────────────────────────
        ctrl_card = tk.Frame(body, bg="white", relief="solid", bd=1, width=300)
        ctrl_card.pack(side=tk.RIGHT, fill=tk.Y)
        ctrl_card.pack_propagate(False)

        tk.Label(ctrl_card, text="TRAINING CONTROLS", font=("Segoe UI", 10, "bold"),
                 bg="white", fg="#7f8c8d").pack(pady=(18, 4), padx=20, anchor="w")

        divider = tk.Frame(ctrl_card, bg="#ecf0f1", height=2)
        divider.pack(fill=tk.X, padx=20, pady=(0, 14))

        # Label entry
        tk.Label(ctrl_card, text="Product Label", font=("Segoe UI", 11, "bold"),
                 bg="white", fg="#2c3e50").pack(anchor="w", padx=20)
        tk.Label(ctrl_card, text="Enter the exact product name for capture or upload.",
                 font=("Segoe UI", 9), bg="white", fg="#95a5a6").pack(anchor="w", padx=20, pady=(2, 6))

        self.ent_train_name = ttk.Entry(ctrl_card, font=("Segoe UI", 13))
        self.ent_train_name.pack(fill=tk.X, padx=20, pady=(0, 4))

        self.attach_training_keyboard(self.root, self.ent_train_name)

        # Training mode selector
        tk.Label(ctrl_card, text="Training Mode", font=("Segoe UI", 10, "bold"),
                 bg="white", fg="#2c3e50").pack(anchor="w", padx=20, pady=(8, 4))
        self.train_mode_var = tk.StringVar(value="capture")
        mode_row = tk.Frame(ctrl_card, bg="white")
        mode_row.pack(fill=tk.X, padx=20, pady=(0, 8))
        self.rb_train_capture = tk.Radiobutton(
            mode_row, text="Capture (3 Cameras)", variable=self.train_mode_var, value="capture",
            command=self.on_training_mode_changed, bg="white", fg="#2c3e50",
            selectcolor="white", activebackground="white", anchor="w"
        )
        self.rb_train_capture.pack(fill=tk.X, anchor="w")
        self.rb_train_upload = tk.Radiobutton(
            mode_row, text="Upload Folder", variable=self.train_mode_var, value="upload",
            command=self.on_training_mode_changed, bg="white", fg="#2c3e50",
            selectcolor="white", activebackground="white", anchor="w"
        )
        self.rb_train_upload.pack(fill=tk.X, anchor="w")

        # Capture count badge
        count_row = tk.Frame(ctrl_card, bg="white")
        count_row.pack(fill=tk.X, padx=20, pady=(10, 4))
        tk.Label(count_row, text="Training actions this session:",
                 font=("Segoe UI", 10), bg="white", fg="#7f8c8d").pack(side=tk.LEFT)
        self._train_count = 0
        self.lbl_train_count = tk.Label(count_row, text="0", font=("Segoe UI", 10, "bold"),
                                        bg=config.ACCENT_COLOR, fg="white", width=4, padx=6)
        self.lbl_train_count.pack(side=tk.RIGHT)

        divider2 = tk.Frame(ctrl_card, bg="#ecf0f1", height=2)
        divider2.pack(fill=tk.X, padx=20, pady=(14, 14))

        # Status badge
        self.lbl_train_status = tk.Label(ctrl_card, text="● Camera Ready",
                                         font=("Segoe UI", 10), bg="white", fg=config.SUCCESS_COLOR,
                                         anchor="w", justify="left", wraplength=250, height=3)
        self.lbl_train_status.pack(fill=tk.X, padx=20, pady=(0, 10))

        # Upload progress (shown only while folder training is running)
        self.train_progress = ttk.Progressbar(ctrl_card, mode="indeterminate")
        self.train_progress.pack(fill=tk.X, padx=20, pady=(0, 10))
        self.train_progress.pack_forget()

        # Dynamic training action button (capture or upload)
        self.btn_train_action = ttk.Button(ctrl_card, text="📷  CAPTURE DATASET IMAGE",
                                           style="Primary.TButton", command=self.run_training_action)
        self.btn_train_action.pack(fill=tk.X, padx=20, pady=(0, 10), ipady=6)
        self.on_training_mode_changed()

        # Instructions
        instr = (
            "Tips:\n"
            "• Capture mode: place product and tap capture\n"
            "• Upload mode: choose a folder of product images\n"
            "• Images are saved under the typed product label"
        )
        tk.Label(ctrl_card, text=instr, font=("Segoe UI", 9), bg="white", fg="#7f8c8d",
                 justify="left", anchor="nw").pack(anchor="w", padx=20, pady=(4, 18))

        self.update_train_cam()

    def update_train_cam(self):
        if not self.running: return
        try:
            frame = self.camera.get_ui_frame()
            if frame is not None:
                img = ImageTk.PhotoImage(image=Image.fromarray(cv2.cvtColor(cv2.resize(frame, (480, 360)), cv2.COLOR_BGR2RGB)))
                self.train_cam_lbl.configure(image=img)
                self.train_cam_lbl.image = img
        except Exception:
            pass
        self.root.after(100, self.update_train_cam)

    def on_training_mode_changed(self):
        self._apply_training_mode_button_text()
        if self._train_task_in_progress:
            return

        mode = self.train_mode_var.get() if hasattr(self, "train_mode_var") else "capture"
        if self._apply_training_ai_status(mode):
            return

        if mode == "upload":
            self.lbl_train_status.config(text="● Upload mode ready", foreground=config.SUCCESS_COLOR)
        else:
            self.lbl_train_status.config(text="● Camera mode ready", foreground=config.SUCCESS_COLOR)

    def _apply_training_mode_button_text(self):
        if not hasattr(self, "btn_train_action"):
            return
        if self.train_mode_var.get() == "upload":
            self.btn_train_action.config(text="📁  UPLOAD TRAINING FOLDER")
        else:
            self.btn_train_action.config(text="📷  CAPTURE DATASET IMAGE")

    def _set_training_busy(self, busy, status_text=None):
        self._train_task_in_progress = bool(busy)
        button_state = "disabled" if busy else "normal"
        radio_state = tk.DISABLED if busy else tk.NORMAL

        if hasattr(self, "btn_train_action"):
            self.btn_train_action.config(state=button_state)
        if hasattr(self, "rb_train_capture"):
            self.rb_train_capture.config(state=radio_state)
        if hasattr(self, "rb_train_upload"):
            self.rb_train_upload.config(state=radio_state)
        if hasattr(self, "ent_train_name"):
            self.ent_train_name.config(state=button_state)

        if busy:
            if not self.train_progress.winfo_ismapped():
                self.train_progress.pack(fill=tk.X, padx=20, pady=(0, 10))
            self.train_progress.start(12)
            if status_text:
                self.lbl_train_status.config(text=f"● {status_text}", foreground=config.ACCENT_COLOR)
        else:
            self.train_progress.stop()
            if self.train_progress.winfo_ismapped():
                self.train_progress.pack_forget()
            self._apply_training_mode_button_text()

    def _get_ai_runtime_status(self):
        if hasattr(self.ai, "get_runtime_status") and callable(self.ai.get_runtime_status):
            try:
                return self.ai.get_runtime_status() or {}
            except Exception as e:
                logger.warning("Training AI status read failed: %s", e)
        return {}

    def _apply_training_ai_status(self, mode):
        status = self._get_ai_runtime_status()
        if not status:
            return False

        if not bool(status.get("feature_extractor_ready", True)):
            self.lbl_train_status.config(
                text="● AI model unavailable. Check TensorFlow/weights setup.",
                foreground=config.DANGER_COLOR
            )
            return True

        if mode == "capture" and int(status.get("profiles_loaded") or 0) <= 0:
            self.lbl_train_status.config(
                text="● Ready to create first AI profiles.",
                foreground=config.WARNING_COLOR
            )
            return True

        return False

    def run_training_action(self):
        if self._train_task_in_progress:
            return
        if self.train_mode_var.get() == "upload":
            self.upload_training_folder()
        else:
            self.capture_images()

    def _collect_training_image_paths(self, folder_path):
        image_exts = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
        paths = []
        for root, _, files in os.walk(folder_path):
            for filename in files:
                ext = os.path.splitext(filename)[1].lower()
                if ext in image_exts:
                    paths.append(os.path.join(root, filename))
        return sorted(paths)

    def upload_training_folder(self):
        if self._train_task_in_progress:
            return

        label = self.ent_train_name.get().strip()
        if not label:
            self.lbl_train_status.config(text="● Please enter a product label.", foreground=config.DANGER_COLOR)
            return

        if self._apply_training_ai_status("upload"):
            return

        folder_path = filedialog.askdirectory(parent=self.root, title="Select Training Image Folder")
        if not folder_path:
            self.lbl_train_status.config(text="● Folder selection canceled.", foreground=config.WARNING_COLOR)
            return

        image_paths = self._collect_training_image_paths(folder_path)
        if not image_paths:
            self.lbl_train_status.config(text="● No supported images found in selected folder.", foreground=config.DANGER_COLOR)
            return

        self._set_training_busy(True, f"Uploading {len(image_paths)} images…")

        def _upload_worker():
            upload_result = None
            upload_error = None
            try:
                upload_result = self.ai.capture_training_data_from_paths(label, image_paths)
            except Exception as e:
                upload_error = str(e)
                logger.warning("Training folder upload error: %s", e)
            self.root.after(0, lambda: self._finish_upload_training(upload_result, upload_error))

        threading.Thread(target=_upload_worker, daemon=True).start()

    def _finish_upload_training(self, upload_result, upload_error):
        self._set_training_busy(False)

        if upload_error:
            self.lbl_train_status.config(text=f"● Error: {upload_error}", foreground=config.DANGER_COLOR)
            return

        upload_result = upload_result or {}
        saved_count = int(upload_result.get("saved_count", 0))
        status_text = upload_result.get("message", "Folder upload completed.")

        if saved_count > 0:
            self._train_count += 1
            self.lbl_train_count.config(text=str(self._train_count))
            status_color = config.SUCCESS_COLOR
        else:
            status_color = config.DANGER_COLOR

        self.lbl_train_status.config(text=f"● {status_text}", foreground=status_color)

    def capture_images(self):
        label = self.ent_train_name.get().strip()
        if not label:
            self.lbl_train_status.config(text="● Please enter a product label.", foreground=config.DANGER_COLOR)
            return

        if self._apply_training_ai_status("capture"):
            status = self._get_ai_runtime_status()
            if not bool(status.get("feature_extractor_ready", True)):
                return

        if hasattr(self.camera, "get_all_raw_frames") and callable(self.camera.get_all_raw_frames):
            frames = self.camera.get_all_raw_frames()
        else:
            frames = [self.camera.get_raw_frame(i) for i in range(3)]

        frames = [frame for frame in frames if frame is not None]
        if not frames:
            self.lbl_train_status.config(text="● No camera frame available.", foreground=config.DANGER_COLOR)
            return

        try:
            # We now use the persistent self.ai instance instead of initializing a new one
            saved_status = self.ai.capture_training_data(label, frames)
            
            self._train_count += 1
            self.lbl_train_count.config(text=str(self._train_count))
            self.lbl_train_status.config(text=f"● {saved_status}", foreground=config.SUCCESS_COLOR)
        except Exception as e:
            logger.warning("Training capture error: %s", e)
            self.lbl_train_status.config(text=f"● Error: {str(e)}", foreground=config.DANGER_COLOR)

    def build_history_tab(self):
        panel = ttk.Frame(self.tab_history, style="Card.TFrame")
        panel.pack(fill=tk.BOTH, expand=True)
        
        bar = ttk.Frame(panel, style="Card.TFrame")
        bar.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(bar, text="Filter Range:", style="Body.TLabel").pack(side=tk.LEFT)
        
        self.filter_var = tk.StringVar(value="All Time")
        cb = ttk.Combobox(bar, textvariable=self.filter_var, values=("Last 7 Days", "Last 30 Days", "All Time"), state="readonly", font=("Segoe UI", 11))
        cb.pack(side=tk.LEFT, padx=10)
        cb.bind("<<ComboboxSelected>>", lambda e: self.refresh_history())
        
        ttk.Button(bar, text="REFRESH DATA", style="Secondary.TButton", command=self.refresh_history).pack(side=tk.RIGHT)
        
        ttk.Button(bar, text="VIEW RECEIPT", style="Primary.TButton", command=self.view_selected_receipt).pack(side=tk.RIGHT, padx=10)
        
        cols = ("Time", "ID", "Items", "Total", "Seller", "Method")
        col_widths = {"Time": 160, "ID": 120, "Items": 60, "Total": 100, "Seller": 150, "Method": 100}
        self.hist_tree = ttk.Treeview(panel, columns=cols, show="headings")
        for col in cols:
            self.hist_tree.heading(col, text=col, anchor="w")
            self.hist_tree.column(col, width=col_widths[col], minwidth=col_widths[col], anchor="w")

        # Tag styles for alternating rows and day-header separators
        self.hist_tree.tag_configure("day_header",
                                     background=config.THEME_COLOR, foreground="white",
                                     font=("Segoe UI", 10, "bold"))
        self.hist_tree.tag_configure("row_even", background="#f8f9fa")
        self.hist_tree.tag_configure("row_odd",  background="white")
        
        sb = ttk.Scrollbar(panel, orient="vertical", command=self.hist_tree.yview)
        self.hist_tree.configure(yscrollcommand=sb.set)
        
        self.hist_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.hist_tree.bind("<Double-1>", self.view_selected_receipt)
        self.refresh_history()

    def refresh_history(self):
        for i in self.hist_tree.get_children():
            self.hist_tree.delete(i)
        days = 7 if "7" in self.filter_var.get() else 30 if "30" in self.filter_var.get() else None
        data = self.db.get_history_grouped(days)
        if not data:
            return

        daily_totals = {}
        for row in data:
            try:
                row_date = str(row[0])[:10]
            except Exception:
                row_date = ""

            try:
                row_total = float(row[3] or 0)
            except (TypeError, ValueError):
                row_total = 0.0
            daily_totals[row_date] = daily_totals.get(row_date, 0.0) + row_total

        current_date = None
        row_index = 0
        for row in data:
            # row[0] is a timestamp string like "2026-03-08 14:22:01"
            try:
                row_date = str(row[0])[:10]
            except Exception:
                row_date = ""

            if row_date != current_date:
                current_date = row_date
                day_total = daily_totals.get(row_date, 0.0)
                # Insert a styled date separator spanning all columns
                self.hist_tree.insert("", "end",
                                      values=(f"  ──  {row_date}  ──", "", "", f"₱ {day_total:.2f}", "", ""),
                                      tags=("day_header",))
                row_index = 0  # reset alternating colour after each header

            tag = "row_even" if row_index % 2 == 0 else "row_odd"
            self.hist_tree.insert("", "end", values=row, tags=(tag,))
            row_index += 1

    def view_selected_receipt(self, event=None):
        if event:
            item_id = self.hist_tree.identify_row(event.y)
            if not item_id: return
            # Skip day-header separator rows
            if "day_header" in self.hist_tree.item(item_id, "tags"):
                return
            self.hist_tree.selection_set(item_id)
            
        selected = self.hist_tree.selection()
        if not selected: 
            self.show_custom_error(self.root, "Selection Required", "Please select a transaction from the list first.")
            return
        
        values = self.hist_tree.item(selected[0], "values")
        time_str = values[0]
        t_id = values[1]
        total_val = values[3]
        seller_val = values[4]
        method_val = values[5]
        
        details = self.db.get_transaction_details(t_id)
        if not details: return
        
        dialog = tk.Toplevel(self.root)
        dialog.configure(bg="white", highlightbackground="#bdc3c7", highlightthickness=2)
        dialog.transient(self.root)
        dialog.overrideredirect(True)
        dialog.attributes('-topmost', True)
        
        dw, dh = 500, 450
        sw = config.SCREEN_MAIN_W
        sh = config.SCREEN_MAIN_H
        dx = (sw - dw) // 2
        dy = (sh - dh) // 2
        dialog.geometry(f"{dw}x{dh}+{dx}+{dy}")
        
        top_bar = tk.Frame(dialog, bg="white")
        top_bar.pack(fill=tk.X, padx=10, pady=(10, 0))
        
        ttk.Label(top_bar, text=f"Receipt: {t_id}", font=("Segoe UI", 12, "bold"), background="white").pack(side=tk.LEFT)
        close_btn = tk.Button(top_bar, text="✖", font=("Segoe UI", 12), bg="#e74c3c", fg="white", relief="flat", command=dialog.destroy, width=3)
        close_btn.pack(side=tk.RIGHT)
        
        ttk.Label(dialog, text=f"Date: {time_str}", background="white").pack(pady=(5, 2))
        ttk.Label(
            dialog,
            text=f"Seller: {seller_val}   Method: {method_val}   Total: ₱ {total_val}",
            background="white"
        ).pack(pady=(0, 5))
        
        frame = tk.Frame(dialog, bg="white")
        frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        cols = ("Product", "Weight", "Subtotal")
        tree = ttk.Treeview(frame, columns=cols, show="headings", height=8)
        for c in cols: tree.heading(c, text=c)
        tree.column("Product", width=150)
        tree.column("Weight", width=100)
        tree.column("Subtotal", width=100)
        
        for item in details:
            name, weight, price = item
            tree.insert("", "end", values=(name, f"{weight:.2f} kg", f"₱ {price:.2f}"))
            
        sb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        
        ttk.Button(dialog, text="Close", command=dialog.destroy, style="Secondary.TButton").pack(pady=15)

        dialog.update_idletasks()
        dialog.grab_set()

    def build_reports_tab(self):
        panel = ttk.Frame(self.tab_report, style="Card.TFrame")
        panel.pack(fill=tk.BOTH, expand=True)

        reports_style = ttk.Style()
        reports_style.configure(
            "ReportsPrimary.TButton",
            font=("Segoe UI", 10, "bold"),
            background=config.ACCENT_COLOR,
            foreground="white",
            borderwidth=1,
            relief="solid",
            padding=(12, 8)
        )
        reports_style.map(
            "ReportsPrimary.TButton",
            background=[("active", "#2980b9"), ("pressed", "#1f618d")]
        )
        reports_style.configure(
            "ReportsSecondary.TButton",
            font=("Segoe UI", 10, "bold"),
            background="white",
            foreground="#2c3e50",
            borderwidth=1,
            relief="solid",
            bordercolor="#dcdde1",
            padding=(12, 8)
        )
        reports_style.map(
            "ReportsSecondary.TButton",
            background=[("active", "#ecf0f1"), ("pressed", "#dfe6e9")]
        )

        status_card = tk.Frame(panel, bg="#f8f9fa", highlightbackground="#dcdde1", highlightthickness=1)
        status_card.pack(fill=tk.X, padx=10, pady=(0, 10))

        status_header = tk.Frame(status_card, bg="#f8f9fa")
        status_header.pack(fill=tk.X, padx=12, pady=(10, 6))
        tk.Label(
            status_header,
            text="Cloud Sync Status",
            font=("Segoe UI", 11, "bold"),
            bg="#f8f9fa",
            fg="#2c3e50"
        ).pack(side=tk.LEFT)

        action_buttons = tk.Frame(status_header, bg="#f8f9fa")
        action_buttons.pack(side=tk.RIGHT)

        action_button_width = 15
        ttk.Button(
            action_buttons,
            text="Refresh",
            style="ReportsSecondary.TButton",
            width=action_button_width,
            command=self.refresh_cloud_sync_status
        ).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(
            action_buttons,
            text="Sync Now",
            style="ReportsPrimary.TButton",
            width=action_button_width,
            command=self.sync_cloud_now
        ).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(
            action_buttons,
            text="Queue Old Sales",
            style="ReportsSecondary.TButton",
            width=action_button_width,
            command=self.backfill_cloud_history
        ).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(
            action_buttons,
            text="Cloud Reports",
            style="ReportsPrimary.TButton",
            width=action_button_width,
            command=self.open_cloud_reports_popup
        ).pack(side=tk.LEFT)

        self.lbl_sync_status = tk.Label(
            status_card,
            text="Sync status loading...",
            font=("Segoe UI", 10),
            bg="#f8f9fa",
            fg="#7f8c8d",
            anchor="w",
            justify="left"
        )
        self.lbl_sync_status.pack(fill=tk.X, padx=12, pady=(0, 10))

        self.refresh_cloud_sync_status()
        self._schedule_sync_status_refresh()

        data = self.db.get_fastest_moving_items()

        if not data:
            ttk.Label(panel, text="No Data Available for Charts", style="Body.TLabel").pack(pady=50)
            return

        charts_frame = tk.Frame(panel, bg="white")
        charts_frame.pack(fill=tk.X, padx=10, pady=5)

        names = [x[0] for x in data]
        volumes = [x[1] for x in data]
        frequencies = [x[2] for x in data]

        fig = Figure(figsize=(10, 4), dpi=90)
        fig.patch.set_facecolor('white')

        ax1 = fig.add_subplot(121)
        ax1.bar(names, volumes, color="#3498db")
        ax1.set_facecolor('white')
        ax1.set_title("Top Products by Volume (kg)", fontsize=11, fontweight='bold')
        ax1.set_xlabel("Product")
        ax1.set_ylabel("Total kg Sold")
        ax1.tick_params(axis='x', rotation=15)

        ax2 = fig.add_subplot(122)
        ax2.bar(names, frequencies, color="#27ae60")
        ax2.set_facecolor('white')
        ax2.set_title("Top Products by Transactions", fontsize=11, fontweight='bold')
        ax2.set_xlabel("Product")
        ax2.set_ylabel("Number of Transactions")
        ax2.tick_params(axis='x', rotation=15)

        fig.tight_layout()
        canvas = FigureCanvasTkAgg(fig, master=charts_frame)
        canvas.get_tk_widget().pack(fill=tk.X)

        ttk.Label(panel, text="Daily Sales Summary", style="SubHeader.TLabel").pack(anchor="w", padx=15, pady=(10, 2))

        summary_frame = tk.Frame(panel, bg="white")
        summary_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        sum_cols = ("Date", "Transactions", "Total Revenue (₱)")
        sum_tree = ttk.Treeview(summary_frame, columns=sum_cols, show="headings", height=5)
        for col in sum_cols:
            sum_tree.heading(col, text=col, anchor="center")
            sum_tree.column(col, anchor="center")

        daily = self.db.get_daily_sales_summary()
        for row in daily:
            sum_tree.insert("", "end", values=row)

        sb = ttk.Scrollbar(summary_frame, orient="vertical", command=sum_tree.yview)
        sum_tree.configure(yscrollcommand=sb.set)
        sum_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

    def refresh_cloud_sync_status(self):
        if not hasattr(self, "lbl_sync_status"):
            return

        queue_status = {}
        try:
            queue_status = self.db.get_sync_queue_status() or {}
        except Exception as e:
            logger.warning("Could not fetch sync queue status: %s", e)

        pending_count = int(queue_status.get("pending_count") or 0)
        failed_count = int(queue_status.get("failed_count") or 0)
        synced_count = int(queue_status.get("synced_count") or 0)
        queue_last_synced = queue_status.get("last_synced_at") or "Never"

        cloud_sync = getattr(self.root, "cloud_sync", None)
        worker_status = cloud_sync.get_status() if cloud_sync is not None else {}
        worker_enabled = bool(worker_status.get("enabled"))
        endpoint_ok = bool(worker_status.get("endpoint_configured"))
        last_sync_at = worker_status.get("last_sync_at") or queue_last_synced
        last_error = str(worker_status.get("last_error") or "").strip()

        mode_text = "Enabled" if worker_enabled else "Disabled (local-only)"
        if worker_enabled and not endpoint_ok:
            mode_text = "Enabled but endpoint is missing"

        text = (
            f"Mode: {mode_text}    Pending: {pending_count}    Failed: {failed_count}    "
            f"Synced: {synced_count}    Last Sync: {last_sync_at}"
        )
        if last_error:
            text = f"{text}\nLast Error: {last_error}"

        color = config.SUCCESS_COLOR if pending_count == 0 and failed_count == 0 else config.WARNING_COLOR
        if failed_count > 0 or (worker_enabled and not endpoint_ok):
            color = config.DANGER_COLOR

        self.lbl_sync_status.config(text=text, fg=color)

    def _schedule_sync_status_refresh(self):
        if not self.running:
            return
        try:
            self.refresh_cloud_sync_status()
        except Exception as e:
            logger.warning("Cloud sync status auto-refresh failed: %s", e)
        self.root.after(5000, self._schedule_sync_status_refresh)

    def sync_cloud_now(self):
        cloud_sync = getattr(self.root, "cloud_sync", None)
        if cloud_sync is None:
            self.lbl_sync_status.config(
                text="Cloud sync worker is unavailable.",
                fg=config.DANGER_COLOR
            )
            return

        self.lbl_sync_status.config(text="Syncing now...", fg=config.ACCENT_COLOR)

        def _sync_worker():
            ok, message = cloud_sync.sync_now()

            def _finish():
                self.refresh_cloud_sync_status()
                if ok:
                    self.lbl_sync_status.config(
                        text=f"{self.lbl_sync_status.cget('text')}\nManual sync: {message}",
                        fg=config.SUCCESS_COLOR
                    )
                else:
                    self.lbl_sync_status.config(
                        text=f"{self.lbl_sync_status.cget('text')}\nManual sync failed: {message}",
                        fg=config.DANGER_COLOR
                    )

            self.root.after(0, _finish)

        threading.Thread(target=_sync_worker, daemon=True).start()

    def backfill_cloud_history(self):
        self.lbl_sync_status.config(text="Backfilling old local sales into sync queue...", fg=config.ACCENT_COLOR)

        def _worker():
            try:
                queued = int(self.db.backfill_sales_to_sync_queue())
                cloud_sync = getattr(self.root, "cloud_sync", None)
                sync_msg = ""
                if cloud_sync is not None:
                    ok, message = cloud_sync.sync_now()
                    sync_msg = f" | sync: {message}" if ok else f" | sync failed: {message}"

                def _finish_ok():
                    self.refresh_cloud_sync_status()
                    self.lbl_sync_status.config(
                        text=f"Backfill complete: queued {queued} historical transaction(s){sync_msg}",
                        fg=config.SUCCESS_COLOR
                    )

                self.root.after(0, _finish_ok)
            except Exception as e:
                def _finish_err():
                    self.refresh_cloud_sync_status()
                    self.lbl_sync_status.config(
                        text=f"Backfill failed: {e}",
                        fg=config.DANGER_COLOR
                    )

                self.root.after(0, _finish_err)

        threading.Thread(target=_worker, daemon=True).start()

    def _get_supabase_config(self):
        supabase_url = str(os.getenv("SUPABASE_URL", "")).strip().rstrip("/")
        supabase_key = str(os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")).strip()
        return supabase_url, supabase_key

    def _fetch_cloud_rows(self, query_path):
        supabase_url, supabase_key = self._get_supabase_config()
        if not supabase_url or not supabase_key:
            return None, "Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY in environment."

        endpoint = f"{supabase_url}/rest/v1/{query_path}"
        headers = {
            "apikey": supabase_key,
            "Authorization": f"Bearer {supabase_key}",
        }
        req = request.Request(endpoint, headers=headers, method="GET")
        try:
            with request.urlopen(req, timeout=12) as response:
                payload = response.read().decode("utf-8", errors="replace")
            return json.loads(payload), ""
        except error.HTTPError as http_error:
            detail = ""
            try:
                detail = http_error.read().decode("utf-8", errors="replace")
            except Exception:
                detail = str(http_error.reason)
            return None, f"HTTP {http_error.code}: {detail}"
        except Exception as e:
            return None, str(e)

    def _fill_cloud_tree(self, tree_widget, rows, columns):
        for item_id in tree_widget.get_children():
            tree_widget.delete(item_id)

        if not rows:
            return

        for row in rows:
            values = [row.get(col_key, "") for col_key, _ in columns]
            tree_widget.insert("", "end", values=values)

    def _show_cloud_transaction_items_popup(self, transaction_id, sale_time, total_value, seller_value, method_value, item_rows):
        dialog = tk.Toplevel(self.root)
        dialog.configure(bg="white", highlightbackground="#bdc3c7", highlightthickness=2)
        dialog.transient(self.root)
        dialog.overrideredirect(True)
        dialog.attributes('-topmost', True)

        dw, dh = 640, 430
        sw = config.SCREEN_MAIN_W
        sh = config.SCREEN_MAIN_H
        dx = (sw - dw) // 2
        dy = (sh - dh) // 2
        dialog.geometry(f"{dw}x{dh}+{dx}+{dy}")

        top_bar = tk.Frame(dialog, bg="white")
        top_bar.pack(fill=tk.X, padx=12, pady=(12, 8))
        ttk.Label(top_bar, text=f"Cloud Receipt: {transaction_id}", font=("Segoe UI", 12, "bold"), background="white").pack(side=tk.LEFT)
        tk.Button(top_bar, text="✖", font=("Segoe UI", 12), bg="#e74c3c", fg="white", relief="flat", command=dialog.destroy, width=3).pack(side=tk.RIGHT)

        info_row = tk.Frame(dialog, bg="white")
        info_row.pack(fill=tk.X, padx=16, pady=(0, 8))

        ttk.Label(info_row, text=f"Date: {sale_time}", background="white").pack(side=tk.LEFT)
        ttk.Label(info_row, text=f"Seller: {seller_value}", background="white").pack(side=tk.LEFT, padx=(16, 0))
        ttk.Label(info_row, text=f"Method: {method_value}", background="white").pack(side=tk.LEFT, padx=(16, 0))
        ttk.Label(info_row, text=f"Total: {total_value}", background="white", font=("Segoe UI", 10, "bold")).pack(side=tk.RIGHT)

        frame = tk.Frame(dialog, bg="white")
        frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 10))
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        cols = ("Product", "Weight", "Subtotal")
        tree = ttk.Treeview(frame, columns=cols, show="headings", height=10)
        for col in cols:
            tree.heading(col, text=col, anchor="center")
            tree.column(col, anchor="center", width=180, minwidth=160, stretch=True)

        for row in item_rows:
            product = row.get("product_name", "")
            try:
                weight = float(row.get("weight") or 0.0)
            except (TypeError, ValueError):
                weight = 0.0
            try:
                subtotal = float(row.get("total_price") or 0.0)
            except (TypeError, ValueError):
                subtotal = 0.0
            tree.insert("", "end", values=(product, f"{weight:.2f} kg", f"₱ {subtotal:.2f}"))

        sb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")

        ttk.Button(dialog, text="Close", style="Secondary.TButton", command=dialog.destroy).pack(pady=(0, 14))
        dialog.grab_set()

    def open_cloud_reports_popup(self):
        popup = tk.Toplevel(self.root)
        popup.configure(bg="white", highlightbackground="#bdc3c7", highlightthickness=2)
        popup.transient(self.root)
        popup.overrideredirect(True)
        popup.attributes('-topmost', True)

        desired_w, desired_h = 900, 700
        sw = config.SCREEN_MAIN_W
        sh = config.SCREEN_MAIN_H
        margin = 8
        dw = min(desired_w, max(640, sw - (margin * 2)))
        dh = min(desired_h, max(420, sh - (margin * 2)))
        dx = max(margin, (sw - dw) // 2)
        dy = max(margin, (sh - dh) // 2)
        popup.geometry(f"{dw}x{dh}+{dx}+{dy}")

        top_bar = tk.Frame(popup, bg="white")
        top_bar.pack(fill=tk.X, padx=10, pady=(10, 0))
        ttk.Label(top_bar, text="Cloud Database Reports", font=("Segoe UI", 12, "bold"), background="white").pack(side=tk.LEFT)
        tk.Button(top_bar, text="✖", font=("Segoe UI", 12), bg="#e74c3c", fg="white", relief="flat", command=popup.destroy, width=3).pack(side=tk.RIGHT)

        body = tk.Frame(popup, bg="white")
        body.pack(fill=tk.BOTH, expand=True, padx=12, pady=10)

        footer = tk.Frame(body, bg="white")
        footer.pack(side=tk.BOTTOM, fill=tk.X, pady=(8, 0))

        cloud_tabs = ttk.Notebook(body)
        cloud_tabs.pack(fill=tk.BOTH, expand=True)

        tab_history = ttk.Frame(cloud_tabs, style="Card.TFrame")
        tab_volume = ttk.Frame(cloud_tabs, style="Card.TFrame")
        tab_freq = ttk.Frame(cloud_tabs, style="Card.TFrame")
        tab_daily = ttk.Frame(cloud_tabs, style="Card.TFrame")

        cloud_tabs.add(tab_history, text=" Cloud History ")
        cloud_tabs.add(tab_volume, text=" Top by Volume ")
        cloud_tabs.add(tab_freq, text=" Top by Frequency ")
        cloud_tabs.add(tab_daily, text=" Daily Summary ")

        history_cols = [("sale_time", "Time"), ("transaction_id", "ID"), ("item_count", "Items"), ("total_amount_php", "Total"), ("seller_name", "Seller"), ("payment_method", "Method")]
        volume_cols = [("product_name", "Product"), ("total_kg_sold", "Total Kg"), ("transactions", "Transactions"), ("revenue_php", "Revenue")]
        freq_cols = [("product_name", "Product"), ("transactions", "Transactions"), ("line_items", "Lines"), ("total_kg_sold", "Total Kg"), ("revenue_php", "Revenue")]
        daily_cols = [("sale_date", "Date"), ("transaction_count", "Transactions"), ("total_revenue_php", "Revenue"), ("total_kg_sold", "Total Kg")]

        def build_tree(parent, columns):
            frame = tk.Frame(parent, bg="white")
            frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
            tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings")

            column_widths = {
                "sale_time": 210,
                "transaction_id": 180,
                "item_count": 90,
                "total_amount_php": 130,
                "seller_name": 140,
                "payment_method": 170,
                "sale_date": 130,
                "transaction_count": 130,
                "total_revenue_php": 150,
                "total_kg_sold": 120,
                "product_name": 180,
                "transactions": 110,
                "line_items": 100,
                "revenue_php": 130,
            }

            for col_key, col_label in columns:
                tree.heading(col_key, text=col_label)
                tree.column(
                    col_key,
                    anchor="center",
                    width=column_widths.get(col_key, 120),
                    minwidth=100,
                    stretch=True,
                )
            sb_local = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
            tree.configure(yscrollcommand=sb_local.set)
            tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            sb_local.pack(side=tk.RIGHT, fill=tk.Y)
            return tree

        tree_history = build_tree(tab_history, history_cols)
        tree_volume = build_tree(tab_volume, volume_cols)
        tree_freq = build_tree(tab_freq, freq_cols)
        tree_daily = build_tree(tab_daily, daily_cols)
        daily_cache = []
        refresh_in_progress = False

        def open_daily_summary_popup():
            rows = list(daily_cache)
            if not rows:
                rows, fetch_err = self._fetch_cloud_rows(
                    "owner_daily_summary?select=sale_date,transaction_count,total_revenue_php,total_kg_sold&limit=365"
                )
                if fetch_err:
                    self.show_custom_error(popup, "Cloud Fetch Error", fetch_err)
                    return

            daily_popup = tk.Toplevel(popup)
            daily_popup.configure(bg="white", highlightbackground="#bdc3c7", highlightthickness=2)
            daily_popup.transient(popup)
            daily_popup.overrideredirect(True)
            daily_popup.attributes("-topmost", True)

            desired_w, desired_h = 780, 580
            sw = config.SCREEN_MAIN_W
            sh = config.SCREEN_MAIN_H
            margin = 18
            pw = min(desired_w, max(620, sw - (margin * 2)))
            ph = min(desired_h, max(420, sh - (margin * 2)))
            px = max(margin, (sw - pw) // 2)
            py = max(margin, (sh - ph) // 2)
            daily_popup.geometry(f"{pw}x{ph}+{px}+{py}")

            title_row = tk.Frame(daily_popup, bg="white")
            title_row.pack(fill=tk.X, padx=12, pady=(12, 8))
            ttk.Label(title_row, text="Daily Sales Summary", font=("Segoe UI", 12, "bold"), background="white").pack(side=tk.LEFT)
            tk.Button(title_row, text="✖", font=("Segoe UI", 12), bg="#e74c3c", fg="white", relief="flat", command=daily_popup.destroy, width=3).pack(side=tk.RIGHT)

            content = tk.Frame(daily_popup, bg="white")
            content.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 10))
            content.columnconfigure(0, weight=1)
            content.rowconfigure(0, weight=1)

            daily_tree = ttk.Treeview(
                content,
                columns=[c[0] for c in daily_cols],
                show="headings"
            )
            daily_col_widths = {
                "sale_date": 180,
                "transaction_count": 170,
                "total_revenue_php": 220,
                "total_kg_sold": 170,
            }
            for col_key, col_label in daily_cols:
                daily_tree.heading(col_key, text=col_label)
                daily_tree.column(
                    col_key,
                    anchor="center",
                    width=daily_col_widths.get(col_key, 160),
                    minwidth=140,
                    stretch=True,
                )

            for row in rows or []:
                daily_tree.insert(
                    "",
                    "end",
                    values=[row.get(col_key, "") for col_key, _ in daily_cols],
                )

            daily_sb = ttk.Scrollbar(content, orient="vertical", command=daily_tree.yview)
            daily_tree.configure(yscrollcommand=daily_sb.set)
            daily_tree.grid(row=0, column=0, sticky="nsew")
            daily_sb.grid(row=0, column=1, sticky="ns")

            ttk.Button(daily_popup, text="Close", style="Secondary.TButton", command=daily_popup.destroy).pack(pady=(0, 12))
            daily_popup.grab_set()

        def show_cloud_history_details(event=None):
            selected = tree_history.selection()
            if not selected:
                return

            values = tree_history.item(selected[0], "values")
            if not values or len(values) < 6:
                return

            sale_time, transaction_id, _, total_value, seller_value, method_value = values
            tx_id = str(transaction_id or "").strip()
            if not tx_id:
                return

            encoded_tx = quote(tx_id, safe="")
            item_rows, item_err = self._fetch_cloud_rows(
                f"owner_receipt_lines?select=product_name,weight,total_price&transaction_id=eq.{encoded_tx}&order=sale_time.asc"
            )
            if item_err:
                self.show_custom_error(popup, "Cloud Fetch Error", item_err)
                return

            self._show_cloud_transaction_items_popup(
                tx_id,
                sale_time,
                total_value,
                seller_value,
                method_value,
                item_rows or []
            )

        tree_history.bind("<Double-1>", show_cloud_history_details)

        status_label = tk.Label(footer, text="", font=("Segoe UI", 10), bg="white", fg="#7f8c8d", anchor="w", justify="left")
        status_label.pack(fill=tk.X, padx=8, pady=(0, 6))

        button_row = tk.Frame(footer, bg="white")
        button_row.pack(fill=tk.X, padx=0, pady=(0, 4))

        def refresh_cloud_reports():
            nonlocal refresh_in_progress
            if refresh_in_progress:
                return

            refresh_in_progress = True
            nonlocal daily_cache
            status_label.config(text="Loading cloud analytics...", fg=config.ACCENT_COLOR)
            popup.update_idletasks()

            def _worker():
                history, err0 = self._fetch_cloud_rows(
                    "owner_history?select=sale_time,transaction_id,item_count,total_amount_php,seller_name,payment_method&limit=100"
                )

                top_volume, err1 = self._fetch_cloud_rows(
                    "owner_top_products_by_volume?select=product_name,total_kg_sold,transactions,revenue_php&limit=10"
                )
                top_freq, err2 = self._fetch_cloud_rows(
                    "owner_top_products_by_transactions?select=product_name,transactions,line_items,total_kg_sold,revenue_php&limit=10"
                )
                daily, err3 = self._fetch_cloud_rows(
                    "owner_daily_summary?select=sale_date,transaction_count,total_revenue_php,total_kg_sold&limit=30"
                )

                def _finish():
                    nonlocal daily_cache
                    nonlocal refresh_in_progress
                    refresh_in_progress = False

                    if not popup.winfo_exists():
                        return

                    if err0 or err1 or err2 or err3:
                        error_messages = [msg for msg in [err0, err1, err2, err3] if msg]
                        status_label.config(
                            text="Cloud fetch error: " + " | ".join(error_messages) + "\nTip: run supabase/bootstrap_cloud.sql in Supabase SQL Editor.",
                            fg=config.DANGER_COLOR
                        )
                        return

                    self._fill_cloud_tree(tree_history, history or [], history_cols)
                    self._fill_cloud_tree(tree_volume, top_volume or [], volume_cols)
                    self._fill_cloud_tree(tree_freq, top_freq or [], freq_cols)
                    self._fill_cloud_tree(tree_daily, daily or [], daily_cols)
                    daily_cache = daily or []
                    status_label.config(text="Cloud reports loaded.", fg=config.SUCCESS_COLOR)

                self.root.after(0, _finish)

            threading.Thread(target=_worker, daemon=True).start()

        ttk.Button(button_row, text="REFRESH CLOUD REPORTS", style="Primary.TButton", command=refresh_cloud_reports).pack(side=tk.LEFT)
        ttk.Button(button_row, text="VIEW CLOUD RECEIPT", style="Secondary.TButton", command=show_cloud_history_details).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(button_row, text="OPEN DAILY SUMMARY", style="Secondary.TButton", command=open_daily_summary_popup).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(button_row, text="CLOSE", style="Secondary.TButton", command=popup.destroy).pack(side=tk.RIGHT)

        refresh_cloud_reports()
        popup.grab_set()

    def build_settings_tab(self):
        panel = ttk.Frame(self.tab_settings, style="Card.TFrame")
        panel.pack(fill=tk.BOTH, expand=True)

        header = tk.Frame(panel, bg="white")
        header.pack(fill=tk.X, padx=20, pady=(20, 10))
        tk.Label(header, text="SETTINGS", font=("Segoe UI", 16, "bold"),
                 bg="white", fg="#2c3e50").pack(anchor="w")
        tk.Label(header, text=f"Unlock with the {self._admin_login_pin_label} to access administrative settings.",
                 font=("Segoe UI", 10), bg="white", fg="#7f8c8d").pack(anchor="w", pady=(2, 0))

        self.settings_lock_prompt = tk.Frame(panel, bg="white")
        self.settings_lock_prompt.pack(fill=tk.X, padx=20, pady=(10, 0))

        pin_row = tk.Frame(self.settings_lock_prompt, bg="white")
        pin_row.pack(anchor="w")
        tk.Label(pin_row, text=self._admin_login_pin_label, font=("Segoe UI", 11, "bold"),
                 bg="white", fg="#2c3e50").pack(side=tk.LEFT, padx=(0, 10))

        self.ent_settings_pin = ttk.Entry(pin_row, show="•", font=("Segoe UI", 13), width=14)
        self.ent_settings_pin.pack(side=tk.LEFT, ipady=4)
        self.ent_settings_pin.bind("<Return>", lambda e: self.unlock_settings_tab())
        self.attach_training_keyboard(self.root, self.ent_settings_pin)

        ttk.Button(pin_row, text="UNLOCK", style="Primary.TButton",
                   command=self.unlock_settings_tab).pack(side=tk.LEFT, padx=(12, 0))

        self.lbl_settings_status = tk.Label(
            self.settings_lock_prompt,
            text=f"Locked. Enter the {self._admin_login_pin_label} to continue.",
            font=("Segoe UI", 10),
            bg="white",
            fg="#7f8c8d"
        )
        self.lbl_settings_status.pack(anchor="w", pady=(10, 0))

        self.settings_content = tk.Frame(
            panel,
            bg="#f8f9fa",
            highlightbackground="#dcdde1",
            highlightthickness=1
        )
        tk.Label(
            self.settings_content,
            text="Settings unlocked. Admin controls are ready.",
            font=("Segoe UI", 13, "bold"),
            bg="#f8f9fa",
            fg="#2c3e50"
        ).pack(anchor="w", padx=20, pady=(20, 6))
        tk.Label(
            self.settings_content,
            text=f"Use the tabs below for Seller Management, {self._admin_login_pin_label}, and Scale Calibration.",
            font=("Segoe UI", 10),
            bg="#f8f9fa",
            fg="#7f8c8d"
        ).pack(anchor="w", padx=20, pady=(0, 12))

        self.settings_subtabs = ttk.Notebook(self.settings_content)
        self.settings_subtabs.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 20))

        settings_style = ttk.Style()
        settings_style.configure(
            "SettingsPrimary.TButton",
            font=("Segoe UI", 10, "bold"),
            background=config.ACCENT_COLOR,
            foreground="white",
            borderwidth=0,
            padding=(12, 8)
        )
        settings_style.map(
            "SettingsPrimary.TButton",
            background=[("active", "#2980b9"), ("pressed", "#1f618d")]
        )
        settings_style.configure(
            "SettingsDanger.TButton",
            font=("Segoe UI", 10, "bold"),
            background=config.DANGER_COLOR,
            foreground="white",
            borderwidth=0,
            padding=(12, 8)
        )
        settings_style.map(
            "SettingsDanger.TButton",
            background=[("active", "#e74c3c"), ("pressed", "#a93226")]
        )
        settings_style.configure(
            "SettingsSecondary.TButton",
            font=("Segoe UI", 10),
            background="white",
            foreground="#2c3e50",
            borderwidth=1,
            relief="solid",
            bordercolor="#dcdde1",
            padding=(12, 8)
        )
        settings_style.map(
            "SettingsSecondary.TButton",
            background=[("active", "#ecf0f1"), ("pressed", "#dfe6e9")]
        )

        seller_tab = tk.Frame(self.settings_subtabs, bg="#f8f9fa")
        admin_tab = tk.Frame(self.settings_subtabs, bg="#f8f9fa")
        scale_tab = tk.Frame(self.settings_subtabs, bg="#f8f9fa")
        self.settings_seller_tab = seller_tab
        self.settings_admin_tab = admin_tab
        self.settings_scale_tab = scale_tab
        self.settings_subtabs.add(seller_tab, text="  Seller Management  ")
        self.settings_subtabs.add(admin_tab, text="  Admin PIN  ")
        self.settings_subtabs.add(scale_tab, text="  Scale Calibration  ")
        self.settings_subtabs.bind("<<NotebookTabChanged>>", self._on_settings_subtab_changed)

        seller_content, seller_canvas = self._create_settings_scrollable_tab(seller_tab)
        admin_content, admin_canvas = self._create_settings_scrollable_tab(admin_tab)
        scale_content, scale_canvas = self._create_settings_scrollable_tab(scale_tab)
        self.settings_seller_canvas = seller_canvas
        self.settings_admin_canvas = admin_canvas
        self.settings_scale_canvas = scale_canvas

        # Seller Account Management
        seller_card = tk.Frame(seller_content, bg="white", relief="solid", bd=1)
        seller_card.pack(fill=tk.BOTH, expand=True, padx=0, pady=(14, 0))

        tk.Label(
            seller_card,
            text="SELLER ACCOUNT MANAGEMENT",
            font=("Segoe UI", 11, "bold"),
            bg="white",
            fg="#2c3e50"
        ).pack(anchor="w", padx=20, pady=(16, 4))
        tk.Frame(seller_card, bg="#ecf0f1", height=2).pack(fill=tk.X, padx=20, pady=(0, 12))

        seller_body = tk.Frame(seller_card, bg="white")
        seller_body.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 14))

        seller_list_section = tk.Frame(seller_body, bg="white")
        seller_list_section.pack(fill=tk.BOTH, expand=True, pady=(0, 12))

        tk.Label(
            seller_list_section,
            text="Seller Accounts",
            font=("Segoe UI", 10, "bold"),
            bg="white",
            fg="#2c3e50"
        ).pack(anchor="w", pady=(0, 6))

        seller_list_frame = tk.Frame(seller_list_section, bg="white")
        seller_list_frame.pack(fill=tk.BOTH, expand=True)

        self.seller_tree = ttk.Treeview(
            seller_list_frame,
            columns=("pin", "name"),
            show="headings",
            height=8,
            selectmode="browse"
        )
        self.seller_tree.heading("pin", text="PIN", anchor="center")
        self.seller_tree.heading("name", text="Name", anchor="w")
        self.seller_tree.column("pin", width=120, anchor="center", stretch=False)
        self.seller_tree.column("name", width=280, anchor="w")
        self.seller_tree.bind("<<TreeviewSelect>>", self.on_seller_selected)

        seller_scroll = ttk.Scrollbar(seller_list_frame, orient="vertical", command=self.seller_tree.yview)
        self.seller_tree.configure(yscrollcommand=seller_scroll.set)
        self.seller_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        seller_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        seller_form = tk.Frame(
            seller_body,
            bg="#f8f9fa",
            highlightbackground="#dcdde1",
            highlightthickness=1
        )
        seller_form.pack(fill=tk.X, pady=(0, 12))

        seller_form_body = tk.Frame(seller_form, bg="#f8f9fa")
        seller_form_body.pack(fill=tk.X, expand=True, padx=16, pady=(12, 12))

        tk.Label(
            seller_form_body,
            text="Seller Details",
            font=("Segoe UI", 10, "bold"),
            bg="#f8f9fa",
            fg="#2c3e50"
        ).pack(anchor="w", pady=(0, 6))

        tk.Label(
            seller_form_body,
            text="Seller Name",
            font=("Segoe UI", 10, "bold"),
            bg="#f8f9fa",
            fg="#2c3e50"
        ).pack(anchor="w")
        self.ent_seller_name = ttk.Entry(seller_form_body, font=("Segoe UI", 12), width=25)
        self.ent_seller_name.pack(fill=tk.X, pady=(4, 12))
        self.ent_seller_name.bind("<Button-1>", self._on_seller_textbox_click)
        self.ent_seller_name.bind("<Return>", lambda e: self.on_seller_form_submit())

        tk.Label(
            seller_form_body,
            text="Seller PIN (4-digit)",
            font=("Segoe UI", 10, "bold"),
            bg="#f8f9fa",
            fg="#2c3e50"
        ).pack(anchor="w")
        self.ent_seller_pin = ttk.Entry(seller_form_body, font=("Segoe UI", 12), width=25)
        self.ent_seller_pin.pack(fill=tk.X, pady=(4, 12))
        self.ent_seller_pin.bind("<Button-1>", self._on_seller_textbox_click)
        self.ent_seller_pin.bind("<Return>", lambda e: self.on_seller_form_submit())

        seller_actions = tk.Frame(
            seller_body,
            bg="#f8f9fa",
            highlightbackground="#dcdde1",
            highlightthickness=1
        )
        seller_actions.pack(fill=tk.X)
        seller_actions_body = tk.Frame(seller_actions, bg="#f8f9fa")
        seller_actions_body.pack(fill=tk.X, padx=16, pady=(10, 12))

        tk.Label(
            seller_actions_body,
            text="Seller Actions",
            font=("Segoe UI", 10, "bold"),
            bg="#f8f9fa",
            fg="#2c3e50"
        ).pack(anchor="w", pady=(0, 8))

        ttk.Button(
            seller_actions_body,
            text="Add Seller",
            style="SettingsPrimary.TButton",
            command=self.on_add_seller
        ).pack(fill=tk.X, pady=(0, 8))
        ttk.Button(
            seller_actions_body,
            text="Update Seller",
            style="SettingsPrimary.TButton",
            command=self.on_update_selected_seller
        ).pack(fill=tk.X, pady=(0, 8))
        ttk.Button(
            seller_actions_body,
            text="Delete Seller",
            style="SettingsDanger.TButton",
            command=self.on_delete_selected_seller
        ).pack(fill=tk.X, pady=(0, 8))
        ttk.Button(
            seller_actions_body,
            text="Clear Form",
            style="SettingsSecondary.TButton",
            command=self.clear_seller_form
        ).pack(fill=tk.X)

        self.lbl_seller_status = tk.Label(
            seller_card,
            text=self._seller_popup_hint_text,
            font=("Segoe UI", 10),
            bg="white",
            fg="#7f8c8d",
            anchor="w",
            justify="left",
            wraplength=980
        )
        self.lbl_seller_status.pack(fill=tk.X, padx=20, pady=(2, 16))

        # Admin Dashboard/Login PIN Management
        admin_card = tk.Frame(
            admin_content,
            bg="white",
            relief="solid",
            bd=1,
            highlightbackground="#2c3e50",
            highlightthickness=1
        )
        admin_card.pack(fill=tk.BOTH, expand=True, padx=0, pady=(14, 0))

        tk.Label(
            admin_card,
            text=f"{self._admin_login_pin_label.upper()} CHANGE",
            font=("Segoe UI", 10, "bold"),
            bg="white",
            fg="#7f8c8d"
        ).pack(anchor="w", padx=20, pady=(16, 4))
        tk.Frame(admin_card, bg="#ecf0f1", height=2).pack(fill=tk.X, padx=20, pady=(0, 12))
        tk.Label(
            admin_card,
            text=self._admin_pin_popup_hint_text,
            font=("Segoe UI", 9),
            bg="white",
            fg="#7f8c8d"
        ).pack(anchor="w", padx=20, pady=(0, 6))
        tk.Label(
            admin_card,
            text="Tap any PIN field to open the compact popup above the keyboard. This is separate from seller PINs.",
            font=("Segoe UI", 9),
            bg="white",
            fg="#2c3e50"
        ).pack(anchor="w", padx=20, pady=(0, 10))

        admin_form = tk.Frame(admin_card, bg="white")
        admin_form.pack(fill=tk.X, padx=20, pady=(0, 10))

        tk.Label(
            admin_form,
            text=f"Current {self._admin_login_pin_label}",
            font=("Segoe UI", 10, "bold"),
            bg="white",
            fg="#2c3e50"
        ).pack(anchor="w")
        self.ent_current_admin_pin = ttk.Entry(admin_form, show="•", font=("Segoe UI", 12), width=24)
        self.ent_current_admin_pin.pack(fill=tk.X, pady=(4, 10), ipady=2)

        tk.Label(
            admin_form,
            text=f"New {self._admin_login_pin_label}",
            font=("Segoe UI", 10, "bold"),
            bg="white",
            fg="#2c3e50"
        ).pack(anchor="w")
        self.ent_new_admin_pin = ttk.Entry(admin_form, show="•", font=("Segoe UI", 12), width=24)
        self.ent_new_admin_pin.pack(fill=tk.X, pady=(4, 10), ipady=2)

        tk.Label(
            admin_form,
            text=f"Confirm New {self._admin_login_pin_label}",
            font=("Segoe UI", 10, "bold"),
            bg="white",
            fg="#2c3e50"
        ).pack(anchor="w")
        self.ent_confirm_admin_pin = ttk.Entry(admin_form, show="•", font=("Segoe UI", 12), width=24)
        self.ent_confirm_admin_pin.pack(fill=tk.X, pady=(4, 0), ipady=2)
        self.ent_confirm_admin_pin.bind("<Return>", lambda e: self.on_change_admin_pin())
        self._bind_admin_inline_popup_fields()

        btn_admin_row = tk.Frame(admin_card, bg="white")
        btn_admin_row.pack(fill=tk.X, padx=20, pady=(0, 10))
        ttk.Button(
            btn_admin_row,
            text="Save PIN",
            style="SettingsPrimary.TButton",
            command=self.on_change_admin_pin
        ).pack(fill=tk.X)

        self.lbl_admin_pin_status = tk.Label(
            admin_card,
            text=self._admin_pin_status_default_text,
            font=("Segoe UI", 9),
            bg="white",
            fg="#7f8c8d",
            anchor="w",
            justify="left",
            wraplength=760
        )
        self.lbl_admin_pin_status.pack(fill=tk.X, padx=20, pady=(0, 12))

        self._build_scale_calibration_card(scale_content)

        self.refresh_seller_accounts()
        self.settings_subtabs.select(self.settings_seller_tab)
        self._on_settings_subtab_changed()

    def _build_scale_calibration_card(self, parent):
        card = tk.Frame(
            parent,
            bg="white",
            relief="solid",
            bd=1,
            highlightbackground="#2c3e50",
            highlightthickness=1
        )
        card.pack(fill=tk.BOTH, expand=True, padx=0, pady=(14, 0))

        tk.Label(
            card,
            text="SCALE CALIBRATION",
            font=("Segoe UI", 11, "bold"),
            bg="white",
            fg="#2c3e50"
        ).pack(anchor="w", padx=20, pady=(16, 4))
        tk.Frame(card, bg="#ecf0f1", height=2).pack(fill=tk.X, padx=20, pady=(0, 12))

        body = tk.Frame(card, bg="white")
        body.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 14))

        instruction = (
            "1) Remove all items from the scale and tap Tare/Zero.\n"
            "2) Place a known test weight.\n"
            "3) Enter the known weight in grams and tap Apply Calibration.\n"
            "No Arduino re-upload is required; factor is saved automatically."
        )
        tk.Label(
            body,
            text=instruction,
            font=("Segoe UI", 10),
            bg="white",
            fg="#2c3e50",
            justify="left",
            anchor="w"
        ).pack(fill=tk.X)

        live_card = tk.Frame(body, bg="#f8f9fa", highlightbackground="#dcdde1", highlightthickness=1)
        live_card.pack(fill=tk.X, pady=(12, 12))
        live_body = tk.Frame(live_card, bg="#f8f9fa")
        live_body.pack(fill=tk.X, padx=14, pady=12)

        tk.Label(
            live_body,
            text="Live Weight",
            font=("Segoe UI", 10, "bold"),
            bg="#f8f9fa",
            fg="#2c3e50"
        ).grid(row=0, column=0, sticky="w")
        self.lbl_scale_live_weight = tk.Label(
            live_body,
            text="0.00 kg",
            font=("Segoe UI", 20, "bold"),
            bg="#f8f9fa",
            fg=config.ACCENT_COLOR
        )
        self.lbl_scale_live_weight.grid(row=1, column=0, sticky="w", pady=(2, 0))

        tk.Label(
            live_body,
            text="Calibration Factor",
            font=("Segoe UI", 10, "bold"),
            bg="#f8f9fa",
            fg="#2c3e50"
        ).grid(row=0, column=1, sticky="w", padx=(30, 0))
        self.lbl_scale_factor = tk.Label(
            live_body,
            text="1.000000",
            font=("Consolas", 16, "bold"),
            bg="#f8f9fa",
            fg="#2c3e50"
        )
        self.lbl_scale_factor.grid(row=1, column=1, sticky="w", padx=(30, 0), pady=(2, 0))

        form = tk.Frame(body, bg="white")
        form.pack(fill=tk.X)
        tk.Label(
            form,
            text="Known Weight (grams)",
            font=("Segoe UI", 10, "bold"),
            bg="white",
            fg="#2c3e50"
        ).grid(row=0, column=0, sticky="w")
        self.ent_scale_known_grams = ttk.Entry(form, font=("Segoe UI", 12), width=18)
        self.ent_scale_known_grams.grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.ent_scale_known_grams.insert(0, "243")
        self.ent_scale_known_grams.bind("<Return>", lambda _e: self.on_apply_scale_calibration())

        btn_row = tk.Frame(body, bg="white")
        btn_row.pack(fill=tk.X, pady=(12, 0))
        ttk.Button(
            btn_row,
            text="Tare / Zero Scale",
            style="SettingsSecondary.TButton",
            command=self.on_scale_tare
        ).pack(side=tk.LEFT)
        ttk.Button(
            btn_row,
            text="Apply Calibration",
            style="SettingsPrimary.TButton",
            command=self.on_apply_scale_calibration
        ).pack(side=tk.LEFT, padx=(10, 0))

        self.lbl_scale_status = tk.Label(
            card,
            text="Ready. Follow the 3-step calibration guide above.",
            font=("Segoe UI", 10),
            bg="white",
            fg="#7f8c8d",
            anchor="w",
            justify="left",
            wraplength=960
        )
        self.lbl_scale_status.pack(fill=tk.X, padx=20, pady=(8, 14))

        self._schedule_scale_live_refresh()

    def _schedule_scale_live_refresh(self):
        if not self.running:
            return

        try:
            if self.scale is None:
                self.lbl_scale_live_weight.config(text="No scale")
                self.lbl_scale_factor.config(text="N/A")
                self.lbl_scale_status.config(
                    text="Scale device is unavailable in Admin mode. Restart app and verify hardware setup.",
                    fg=config.DANGER_COLOR
                )
            else:
                weight = float(self.scale.get_weight())
                factor = float(self.scale.get_calibration_factor()) if hasattr(self.scale, "get_calibration_factor") else 1.0
                self.lbl_scale_live_weight.config(text=f"{weight:.2f} kg")
                self.lbl_scale_factor.config(text=f"{factor:.6f}")
        except Exception as e:
            logger.warning("Scale live refresh failed: %s", e)

        self.root.after(250, self._schedule_scale_live_refresh)

    def on_scale_tare(self):
        if self.scale is None:
            self.lbl_scale_status.config(text="Scale device is unavailable.", fg=config.DANGER_COLOR)
            return

        def _do_tare():
            try:
                self.scale.tare()
                self.root.after(0, lambda: self.lbl_scale_status.config(
                    text="Scale tared successfully. Place known weight to continue calibration.",
                    fg=config.SUCCESS_COLOR
                ))
            except Exception as e:
                logger.warning("Scale tare failed: %s", e)
                self.root.after(0, lambda: self.lbl_scale_status.config(
                    text="Scale tare failed. Check connection and try again.",
                    fg=config.DANGER_COLOR
                ))

        threading.Thread(target=_do_tare, daemon=True).start()

    def on_apply_scale_calibration(self):
        if self.scale is None:
            self.lbl_scale_status.config(text="Scale device is unavailable.", fg=config.DANGER_COLOR)
            return

        grams_text = self.ent_scale_known_grams.get().strip()
        try:
            known_grams = float(grams_text)
        except ValueError:
            self.lbl_scale_status.config(text="Enter a valid known weight in grams.", fg=config.WARNING_COLOR)
            return

        if known_grams <= 0:
            self.lbl_scale_status.config(text="Known weight must be greater than zero.", fg=config.WARNING_COLOR)
            return

        known_kg = known_grams / 1000.0
        measured_kg = float(self.scale.get_weight())

        if measured_kg <= 0.005:
            self.lbl_scale_status.config(
                text="Measured weight is too low. Place the known weight on the scale first.",
                fg=config.WARNING_COLOR
            )
            return

        current_factor = float(self.scale.get_calibration_factor()) if hasattr(self.scale, "get_calibration_factor") else 1.0
        ratio = known_kg / measured_kg
        new_factor = current_factor * ratio

        if not hasattr(self.scale, "set_calibration_factor") or not self.scale.set_calibration_factor(new_factor, persist=True):
            self.lbl_scale_status.config(text="Failed to save calibration factor.", fg=config.DANGER_COLOR)
            return

        try:
            self.scale.tare()
        except Exception:
            pass

        self.lbl_scale_status.config(
            text=(
                f"Calibration saved. Measured {measured_kg*1000.0:.1f} g vs known {known_grams:.1f} g. "
                f"Factor updated {current_factor:.6f} -> {new_factor:.6f}."
            ),
            fg=config.SUCCESS_COLOR
        )

    def unlock_settings_tab(self):
        pin = self.ent_settings_pin.get().strip()
        if not pin:
            self.lbl_settings_status.config(
                text=f"Please enter the {self._admin_login_pin_label}.",
                fg=config.WARNING_COLOR
            )
            return

        try:
            is_valid_pin = bool(self.db.verify_admin_pin(pin))
        except Exception as e:
            logger.warning("Admin PIN verification failed: %s", e)
            self.lbl_settings_status.config(
                text=f"Unable to verify the {self._admin_login_pin_label} right now.",
                fg=config.DANGER_COLOR
            )
            return

        if is_valid_pin:
            self.settings_lock_prompt.pack_forget()
            if not self.settings_content.winfo_manager():
                self.settings_content.pack(fill=tk.BOTH, expand=True, padx=20, pady=(10, 20))
            self.ent_settings_pin.delete(0, tk.END)
            self.refresh_seller_accounts()
            self.clear_seller_form()
            self.lbl_admin_pin_status.config(
                text=self._admin_pin_status_default_text,
                fg="#7f8c8d"
            )
            self.ent_current_admin_pin.delete(0, tk.END)
            self.ent_new_admin_pin.delete(0, tk.END)
            self.ent_confirm_admin_pin.delete(0, tk.END)
            if hasattr(self, "settings_subtabs") and self.settings_subtabs.winfo_exists():
                self.settings_subtabs.select(self.settings_seller_tab)
                self._on_settings_subtab_changed()
        else:
            self.lbl_settings_status.config(
                text=f"Invalid {self._admin_login_pin_label}. Access denied.",
                fg=config.DANGER_COLOR
            )
            self.ent_settings_pin.focus_set()
            self.ent_settings_pin.selection_range(0, tk.END)

    def refresh_seller_accounts(self, selected_pin=None):
        if not hasattr(self, "seller_tree"):
            return

        if selected_pin is None:
            current_sel = self.seller_tree.selection()
            if current_sel:
                current_vals = self.seller_tree.item(current_sel[0], "values")
                if current_vals:
                    selected_pin = str(current_vals[0])

        for item in self.seller_tree.get_children():
            self.seller_tree.delete(item)

        try:
            sellers = self.db.get_seller_accounts()
        except Exception as e:
            logger.warning("Failed to load seller accounts: %s", e)
            self.lbl_seller_status.config(text="Unable to load seller accounts right now.", fg=config.DANGER_COLOR)
            return

        selected_item = None
        for pin, name in sellers:
            item_id = self.seller_tree.insert("", tk.END, values=(str(pin), str(name)))
            if selected_pin and str(pin) == str(selected_pin):
                selected_item = item_id

        if selected_item:
            self.seller_tree.selection_set(selected_item)
            self.seller_tree.focus(selected_item)

    def on_seller_selected(self, event=None):
        if not hasattr(self, "seller_tree"):
            return

        selected = self.seller_tree.selection()
        if not selected:
            return

        values = self.seller_tree.item(selected[0], "values")
        if len(values) < 2:
            return

        pin, name = str(values[0]), str(values[1])
        self.ent_seller_name.delete(0, tk.END)
        self.ent_seller_name.insert(0, name)
        self.ent_seller_pin.delete(0, tk.END)
        self.ent_seller_pin.insert(0, pin)
        self.lbl_seller_status.config(text=f"Loaded seller account: {name} ({pin}).", fg="#7f8c8d")

    def _on_seller_textbox_click(self, event=None):
        popup = getattr(self, "seller_editor_popup", None)
        if popup and popup.winfo_exists():
            try:
                popup.lift()
                popup.focus_force()
            except tk.TclError:
                pass
            return "break"

        self.on_seller_form_submit()
        return "break"

    def _bind_admin_inline_popup_fields(self):
        self._bind_admin_inline_popup_field(self.ent_current_admin_pin, "current")
        self._bind_admin_inline_popup_field(self.ent_new_admin_pin, "new")
        self._bind_admin_inline_popup_field(self.ent_confirm_admin_pin, "confirm")

    def _bind_admin_inline_popup_field(self, entry_widget, focus_target):
        entry_widget.bind(
            "<Button-1>",
            lambda event, target=focus_target: self._open_admin_popup_from_inline(target)
        )
        entry_widget.bind(
            "<FocusIn>",
            lambda event, target=focus_target: self._open_admin_popup_from_inline(target)
        )

    def _open_admin_popup_from_inline(self, focus_target="current"):
        popup = getattr(self, "admin_pin_popup", None)
        if popup and popup.winfo_exists():
            try:
                popup.lift()
                popup.focus_force()
            except tk.TclError:
                pass
            return "break"

        self.show_admin_pin_change_popup(initial_focus=focus_target)
        return "break"

    def clear_seller_form(self, reset_status=True):
        if hasattr(self, "ent_seller_name"):
            self.ent_seller_name.delete(0, tk.END)
        if hasattr(self, "ent_seller_pin"):
            self.ent_seller_pin.delete(0, tk.END)
        if hasattr(self, "seller_tree"):
            self.seller_tree.selection_remove(self.seller_tree.selection())
        if reset_status and hasattr(self, "lbl_seller_status"):
            self.lbl_seller_status.config(
                text=self._seller_popup_hint_text,
                fg="#7f8c8d"
            )

    def _save_add_seller(self, pin, name):
        try:
            success, message = self.db.upsert_seller_account(pin, name)
        except Exception as e:
            logger.warning("Seller account add failed: %s", e)
            success = False
            message = "Unable to save seller account right now."

        status_color = config.SUCCESS_COLOR if success else config.DANGER_COLOR
        self.lbl_seller_status.config(text=message, fg=status_color)
        if success:
            self.refresh_seller_accounts(selected_pin=pin)
            self.on_seller_selected()
            self.lbl_seller_status.config(text=message, fg=config.SUCCESS_COLOR)
        return success, message, status_color

    def _save_update_seller(self, current_pin, new_pin, new_name):
        try:
            success, message = self.db.update_seller_account(current_pin, new_pin, new_name)
        except Exception as e:
            logger.warning("Seller account update failed: %s", e)
            success = False
            message = "Unable to update seller account right now."

        status_color = config.SUCCESS_COLOR if success else config.DANGER_COLOR
        if not success and "Select" in message:
            status_color = config.WARNING_COLOR
        self.lbl_seller_status.config(text=message, fg=status_color)
        if success:
            self.refresh_seller_accounts(selected_pin=new_pin)
            self.on_seller_selected()
            self.lbl_seller_status.config(text=message, fg=config.SUCCESS_COLOR)
        return success, message, status_color

    def _close_seller_editor_popup(self):
        popup = getattr(self, "seller_editor_popup", None)
        keyboard = getattr(self, "seller_editor_keyboard", None)

        self.seller_editor_popup = None
        self.seller_editor_keyboard = None

        if keyboard and keyboard.winfo_exists():
            try:
                keyboard.withdraw()
            except tk.TclError:
                pass
            try:
                keyboard.destroy()
            except tk.TclError:
                pass

        if popup and popup.winfo_exists():
            try:
                popup.grab_release()
            except tk.TclError:
                pass
            popup.destroy()

    def show_seller_editor_popup(self, mode="add"):
        mode = "update" if mode == "update" else "add"
        selected_pin = ""
        selected_name = ""

        if mode == "update":
            selected = self.seller_tree.selection()
            if not selected:
                self.lbl_seller_status.config(text="Select a seller account to update.", fg=config.WARNING_COLOR)
                return

            values = self.seller_tree.item(selected[0], "values")
            if len(values) < 2:
                self.lbl_seller_status.config(text="Select a valid seller account to update.", fg=config.WARNING_COLOR)
                return
            selected_pin = str(values[0]).strip()
            selected_name = str(values[1]).strip()

        if hasattr(self, "shared_vk") and self.shared_vk.winfo_exists():
            self.shared_vk.withdraw()

        self._close_seller_editor_popup()

        dialog = tk.Toplevel(self.root)
        dialog.configure(bg="white", highlightbackground="#bdc3c7", highlightthickness=2)
        dialog.transient(self.root)
        dialog.overrideredirect(True)
        dialog.attributes("-topmost", True)
        dialog.withdraw()

        keyboard = VirtualKeyboard(dialog)
        self.seller_editor_popup = dialog
        self.seller_editor_keyboard = keyboard

        closing = {"active": False}
        popup_ready = {"visible": False}

        def close_dialog(event=None):
            if closing["active"]:
                return "break"
            closing["active"] = True
            if not ent_name.get().strip() and not ent_pin.get().strip() and hasattr(self, "lbl_seller_status"):
                self.lbl_seller_status.config(text=self._seller_popup_hint_text, fg="#7f8c8d")
            self._close_seller_editor_popup()
            return "break"

        def focus_field(entry_widget):
            if keyboard.winfo_exists():
                keyboard.deiconify()
                keyboard.set_target(entry_widget)
            entry_widget.focus_set()

        def on_keyboard_hide(event=None):
            if closing["active"] or not popup_ready["visible"]:
                return
            if not ent_name.get().strip() and not ent_pin.get().strip():
                close_dialog()

        title_text = "Update Seller Account" if mode == "update" else "Add Seller Account"
        action_text = "Update Seller" if mode == "update" else "Add Seller"

        top_bar = tk.Frame(dialog, bg="white")
        top_bar.pack(fill=tk.X, padx=10, pady=(10, 0))
        ttk.Label(top_bar, text=title_text, font=("Segoe UI", 12, "bold"), background="white").pack(side=tk.LEFT)
        tk.Button(
            top_bar,
            text="✖",
            font=("Segoe UI", 12),
            bg="#e74c3c",
            fg="white",
            relief="flat",
            command=close_dialog,
            width=3
        ).pack(side=tk.RIGHT)

        body = tk.Frame(dialog, bg="white")
        body.pack(fill=tk.BOTH, expand=True, padx=14, pady=(12, 8))

        tk.Label(body, text="Seller Name", font=("Segoe UI", 10, "bold"), bg="white", fg="#2c3e50").pack(anchor="w")
        ent_name = ttk.Entry(body, font=("Segoe UI", 12), width=28)
        ent_name.pack(fill=tk.X, pady=(4, 10))

        tk.Label(body, text="Seller PIN (4-digit)", font=("Segoe UI", 10, "bold"), bg="white", fg="#2c3e50").pack(anchor="w")
        ent_pin = ttk.Entry(body, font=("Segoe UI", 12), width=28)
        ent_pin.pack(fill=tk.X, pady=(4, 10))

        if mode == "update":
            ent_name.insert(0, selected_name)
            ent_pin.insert(0, selected_pin)

        popup_status = tk.Label(
            body,
            text="",
            font=("Segoe UI", 10),
            bg="white",
            fg="#7f8c8d",
            anchor="w",
            justify="left",
            wraplength=360
        )
        popup_status.pack(fill=tk.X)

        btn_row = tk.Frame(dialog, bg="white")
        btn_row.pack(fill=tk.X, padx=14, pady=(2, 14))
        ttk.Button(btn_row, text="Back", style="Secondary.TButton", command=close_dialog).pack(side=tk.RIGHT)
        ttk.Button(btn_row, text=action_text, style="Primary.TButton", command=lambda: submit_editor()).pack(side=tk.RIGHT, padx=(0, 8))

        def submit_editor(event=None):
            seller_name = ent_name.get().strip()
            seller_pin = ent_pin.get().strip()

            if mode == "update":
                success, message, color = self._save_update_seller(selected_pin, seller_pin, seller_name)
            else:
                success, message, color = self._save_add_seller(seller_pin, seller_name)

            popup_status.config(text=message, fg=color)
            if success:
                close_dialog()
            else:
                if "Name" in message:
                    focus_field(ent_name)
                else:
                    focus_field(ent_pin)
            return "break"

        ent_name.bind("<Button-1>", lambda e: focus_field(ent_name))
        ent_pin.bind("<Button-1>", lambda e: focus_field(ent_pin))
        ent_name.bind("<Return>", lambda e: focus_field(ent_pin))
        ent_pin.bind("<Return>", submit_editor)
        dialog.bind("<Escape>", close_dialog)
        keyboard.bind("<Unmap>", on_keyboard_hide)

        dialog.update_idletasks()
        sw = config.SCREEN_MAIN_W
        sh = config.SCREEN_MAIN_H
        dw = 420
        dh = dialog.winfo_reqheight()
        kh = 300
        keyboard_top = sh - kh - config.TASKBAR_H
        padding = 20
        dx = (sw - dw) // 2
        dy = max(20, keyboard_top - dh - padding)
        dialog.geometry(f"{dw}x{dh}+{dx}+{dy}")
        dialog.deiconify()
        dialog.grab_set()
        popup_ready["visible"] = True
        focus_field(ent_name if mode == "add" else ent_pin)

    def on_seller_form_submit(self):
        selected = self.seller_tree.selection() if hasattr(self, "seller_tree") else ()
        if selected:
            self.show_seller_editor_popup(mode="update")
        else:
            self.show_seller_editor_popup(mode="add")

    def on_add_seller(self):
        self.show_seller_editor_popup(mode="add")

    def on_update_selected_seller(self):
        self.show_seller_editor_popup(mode="update")

    def on_add_update_seller(self):
        self.on_seller_form_submit()

    def show_seller_delete_confirmation(self, seller_name, pin):
        confirm_win = tk.Toplevel(self.root)
        confirm_win.configure(bg="white", highlightbackground="#c0392b", highlightthickness=2)
        confirm_win.transient(self.root)
        confirm_win.overrideredirect(True)
        confirm_win.attributes("-topmost", True)
        confirm_win.withdraw()

        result = {"confirmed": False}

        def close_dialog():
            try:
                confirm_win.grab_release()
            except tk.TclError:
                pass
            if confirm_win.winfo_exists():
                confirm_win.destroy()

        def on_confirm(event=None):
            result["confirmed"] = True
            close_dialog()

        def on_cancel(event=None):
            close_dialog()

        header = tk.Frame(confirm_win, bg="#c0392b")
        header.pack(fill=tk.X)
        tk.Label(
            header,
            text="Confirm Seller Deletion",
            font=("Segoe UI", 11, "bold"),
            bg="#c0392b",
            fg="white"
        ).pack(side=tk.LEFT, padx=12, pady=9)

        body = tk.Frame(confirm_win, bg="white")
        body.pack(fill=tk.BOTH, expand=True, padx=14, pady=(12, 8))
        tk.Label(
            body,
            text=f"Delete seller account '{seller_name}' ({pin})?",
            font=("Segoe UI", 11),
            bg="white",
            fg="#2c3e50",
            justify="left",
            wraplength=360
        ).pack(anchor="w")
        tk.Label(
            body,
            text="This action cannot be undone.",
            font=("Segoe UI", 10),
            bg="white",
            fg="#7f8c8d"
        ).pack(anchor="w", pady=(8, 0))

        btn_row = tk.Frame(confirm_win, bg="white")
        btn_row.pack(fill=tk.X, padx=14, pady=(2, 14))
        ttk.Button(btn_row, text="Cancel", style="Secondary.TButton", command=on_cancel).pack(side=tk.RIGHT)
        ttk.Button(btn_row, text="Delete", style="Danger.TButton", command=on_confirm).pack(side=tk.RIGHT, padx=(0, 8))

        confirm_win.bind("<Escape>", on_cancel)
        confirm_win.bind("<Return>", on_confirm)

        self.root.update_idletasks()
        cw, ch = 390, 185
        cx = self.root.winfo_x() + (self.root.winfo_width() - cw) // 2
        cy = self.root.winfo_y() + (self.root.winfo_height() - ch) // 2
        confirm_win.geometry(f"{cw}x{ch}+{cx}+{cy}")
        confirm_win.deiconify()
        confirm_win.grab_set()
        confirm_win.focus_force()
        self.root.wait_window(confirm_win)
        return result["confirmed"]

    def on_delete_selected_seller(self):
        selected = self.seller_tree.selection()
        if not selected:
            self.lbl_seller_status.config(text="Select a seller account to delete.", fg=config.WARNING_COLOR)
            return

        values = self.seller_tree.item(selected[0], "values")
        if len(values) < 1:
            self.lbl_seller_status.config(text="Select a valid seller account to delete.", fg=config.WARNING_COLOR)
            return

        pin = str(values[0]).strip()
        seller_name = str(values[1]).strip() if len(values) > 1 else "this seller"

        try:
            sellers = self.db.get_seller_accounts()
        except Exception as e:
            logger.warning("Failed to load seller accounts for deletion: %s", e)
            self.lbl_seller_status.config(text="Unable to verify seller accounts right now.", fg=config.DANGER_COLOR)
            return

        if len(sellers) <= 1 and any(str(seller_pin) == pin for seller_pin, _ in sellers):
            self.lbl_seller_status.config(
                text="Cannot delete the last remaining seller account.",
                fg=config.WARNING_COLOR
            )
            return

        should_delete = self.show_seller_delete_confirmation(seller_name, pin)
        if not should_delete:
            self.lbl_seller_status.config(text="Delete cancelled.", fg="#7f8c8d")
            return

        try:
            success, message = self.db.delete_seller_account(pin)
        except Exception as e:
            logger.warning("Seller account delete failed: %s", e)
            self.lbl_seller_status.config(text="Unable to delete seller account right now.", fg=config.DANGER_COLOR)
            return

        self.lbl_seller_status.config(text=message, fg=config.SUCCESS_COLOR if success else config.DANGER_COLOR)
        if success:
            self.refresh_seller_accounts()
            self.clear_seller_form(reset_status=False)
            self.lbl_seller_status.config(text=message, fg=config.SUCCESS_COLOR)

    def _set_admin_pin_status(self, message, color, popup_status_label=None):
        if hasattr(self, "lbl_admin_pin_status"):
            try:
                if self.lbl_admin_pin_status.winfo_exists():
                    self.lbl_admin_pin_status.config(text=message, fg=color)
            except tk.TclError:
                pass

        if popup_status_label is not None:
            try:
                if popup_status_label.winfo_exists():
                    popup_status_label.config(text=message, fg=color)
            except tk.TclError:
                pass

    def _run_admin_pin_change(self, current_pin, new_pin, confirm_pin, popup_status_label=None):
        try:
            success, message = self.db.change_admin_pin(current_pin, new_pin, confirm_pin)
        except Exception as e:
            logger.warning("Admin PIN update failed: %s", e)
            success = False
            message = f"Unable to change the {self._admin_login_pin_label} right now."

        status_color = config.SUCCESS_COLOR if success else config.DANGER_COLOR
        self._set_admin_pin_status(message, status_color, popup_status_label=popup_status_label)
        return success, message, status_color

    def _close_admin_pin_change_popup(self):
        popup = getattr(self, "admin_pin_popup", None)
        keyboard = getattr(self, "admin_pin_keyboard", None)

        self.admin_pin_popup = None
        self.admin_pin_keyboard = None

        if keyboard and keyboard.winfo_exists():
            try:
                keyboard.withdraw()
            except tk.TclError:
                pass
            try:
                keyboard.destroy()
            except tk.TclError:
                pass

        if popup and popup.winfo_exists():
            try:
                popup.grab_release()
            except tk.TclError:
                pass
            popup.destroy()

    def show_admin_pin_change_popup(self, initial_focus="current"):
        if hasattr(self, "shared_vk") and self.shared_vk.winfo_exists():
            self.shared_vk.withdraw()

        self._close_admin_pin_change_popup()

        dialog = tk.Toplevel(self.root)
        dialog.configure(bg="white", highlightbackground="#bdc3c7", highlightthickness=2)
        dialog.transient(self.root)
        dialog.overrideredirect(True)
        dialog.attributes("-topmost", True)
        dialog.withdraw()

        keyboard = VirtualKeyboard(dialog)
        self.admin_pin_popup = dialog
        self.admin_pin_keyboard = keyboard

        closing = {"active": False}

        def close_dialog(event=None):
            if closing["active"]:
                return "break"
            closing["active"] = True
            self._close_admin_pin_change_popup()
            if hasattr(self, "settings_content") and self.settings_content.winfo_exists():
                try:
                    self.settings_content.focus_set()
                except tk.TclError:
                    pass
            return "break"

        def focus_field(entry_widget):
            if keyboard.winfo_exists():
                keyboard.deiconify()
                keyboard.set_target(entry_widget)
            entry_widget.focus_set()
            return "break"

        top_bar = tk.Frame(dialog, bg="white")
        top_bar.pack(fill=tk.X, padx=10, pady=(10, 0))
        ttk.Label(
            top_bar,
            text=f"Change {self._admin_login_pin_label}",
            font=("Segoe UI", 12, "bold"),
            background="white"
        ).pack(side=tk.LEFT)
        tk.Button(
            top_bar,
            text="✖",
            font=("Segoe UI", 12),
            bg="#e74c3c",
            fg="white",
            relief="flat",
            command=close_dialog,
            width=3
        ).pack(side=tk.RIGHT)

        body = tk.Frame(dialog, bg="white")
        body.pack(fill=tk.BOTH, expand=True, padx=14, pady=(12, 8))

        tk.Label(
            body,
            text=f"Current {self._admin_login_pin_label}",
            font=("Segoe UI", 10, "bold"),
            bg="white",
            fg="#2c3e50"
        ).pack(anchor="w")
        ent_current = ttk.Entry(body, show="•", font=("Segoe UI", 12), width=28)
        ent_current.pack(fill=tk.X, pady=(4, 10))

        tk.Label(
            body,
            text=f"New {self._admin_login_pin_label}",
            font=("Segoe UI", 10, "bold"),
            bg="white",
            fg="#2c3e50"
        ).pack(anchor="w")
        ent_new = ttk.Entry(body, show="•", font=("Segoe UI", 12), width=28)
        ent_new.pack(fill=tk.X, pady=(4, 10))

        tk.Label(
            body,
            text=f"Confirm New {self._admin_login_pin_label}",
            font=("Segoe UI", 10, "bold"),
            bg="white",
            fg="#2c3e50"
        ).pack(anchor="w")
        ent_confirm = ttk.Entry(body, show="•", font=("Segoe UI", 12), width=28)
        ent_confirm.pack(fill=tk.X, pady=(4, 10))

        if hasattr(self, "ent_current_admin_pin"):
            ent_current.insert(0, self.ent_current_admin_pin.get().strip())
        if hasattr(self, "ent_new_admin_pin"):
            ent_new.insert(0, self.ent_new_admin_pin.get().strip())
        if hasattr(self, "ent_confirm_admin_pin"):
            ent_confirm.insert(0, self.ent_confirm_admin_pin.get().strip())

        popup_status = tk.Label(
            body,
            text=f"{self._admin_pin_popup_hint_text} Enter your current PIN to authorize the change.",
            font=("Segoe UI", 10),
            bg="white",
            fg="#7f8c8d",
            anchor="w",
            justify="left",
            wraplength=400
        )
        popup_status.pack(fill=tk.X)

        btn_row = tk.Frame(dialog, bg="white")
        btn_row.pack(fill=tk.X, padx=14, pady=(2, 14))
        ttk.Button(btn_row, text="Back", style="Secondary.TButton", command=close_dialog).pack(side=tk.RIGHT)
        ttk.Button(
            btn_row,
            text=f"Change {self._admin_login_pin_label}",
            style="Primary.TButton",
            command=lambda: submit_change()
        ).pack(side=tk.RIGHT, padx=(0, 8))

        def submit_change(event=None):
            current_pin = ent_current.get().strip()
            new_pin = ent_new.get().strip()
            confirm_pin = ent_confirm.get().strip()

            success, message, _ = self._run_admin_pin_change(
                current_pin,
                new_pin,
                confirm_pin,
                popup_status_label=popup_status
            )
            if success:
                if hasattr(self, "ent_current_admin_pin"):
                    self.ent_current_admin_pin.delete(0, tk.END)
                if hasattr(self, "ent_new_admin_pin"):
                    self.ent_new_admin_pin.delete(0, tk.END)
                if hasattr(self, "ent_confirm_admin_pin"):
                    self.ent_confirm_admin_pin.delete(0, tk.END)
                close_dialog()
            else:
                lower_message = message.lower()
                if "current" in lower_message:
                    focus_field(ent_current)
                elif "confirm" in lower_message:
                    focus_field(ent_confirm)
                else:
                    focus_field(ent_new)
            return "break"

        ent_current.bind("<Button-1>", lambda event: focus_field(ent_current))
        ent_new.bind("<Button-1>", lambda event: focus_field(ent_new))
        ent_confirm.bind("<Button-1>", lambda event: focus_field(ent_confirm))

        ent_current.bind("<Return>", lambda event: focus_field(ent_new))
        ent_new.bind("<Return>", lambda event: focus_field(ent_confirm))
        ent_confirm.bind("<Return>", submit_change)
        dialog.bind("<Escape>", close_dialog)

        dialog.update_idletasks()
        sw = config.SCREEN_MAIN_W
        sh = config.SCREEN_MAIN_H
        dw = 460
        dh = dialog.winfo_reqheight()
        kh = 300
        keyboard_top = sh - kh - config.TASKBAR_H
        padding = 20
        dx = (sw - dw) // 2
        dy = max(20, keyboard_top - dh - padding)
        dialog.geometry(f"{dw}x{dh}+{dx}+{dy}")
        dialog.deiconify()
        dialog.grab_set()
        focus_targets = {
            "current": ent_current,
            "new": ent_new,
            "confirm": ent_confirm
        }
        focus_field(focus_targets.get(initial_focus, ent_current))

    def on_change_admin_pin(self):
        current_pin = self.ent_current_admin_pin.get().strip()
        new_pin = self.ent_new_admin_pin.get().strip()
        confirm_pin = self.ent_confirm_admin_pin.get().strip()

        success, _, _ = self._run_admin_pin_change(current_pin, new_pin, confirm_pin)
        if success:
            self.ent_current_admin_pin.delete(0, tk.END)
            self.ent_new_admin_pin.delete(0, tk.END)
            self.ent_confirm_admin_pin.delete(0, tk.END)

