import tkinter as tk
from tkinter import ttk
import config

class LoginWindow:
    def __init__(self, root, db, on_login_success, shutdown_callback=None):
        self.root = root
        self.db = db
        self.on_login_success = on_login_success
        self.shutdown_callback = shutdown_callback
        
        # Ensure background matches theme
        self.root.configure(bg="#f4f6f9")
        
        self.setup_ui()

    def setup_ui(self):
        # Using place(relx=0.5, rely=0.5) ensures PERFECT CENTERING
        # relative to the 1280x800 window.
        main_frame = ttk.Frame(self.root, style="Main.TFrame")
        main_frame.pack(fill="both", expand=True)
        
        # Parented to main_frame so it renders on top of the background
        if self.shutdown_callback:
            btn_exit = tk.Button(main_frame, text="⏻", font=("Segoe UI", 16, "bold"), 
                                 bg="#c0392b", fg="white", bd=0, 
                                 command=self.shutdown_callback)
            
            # Use relative placement (relx=1.0) anchored to the North-East (ne)
            btn_exit.place(relx=1.0, rely=0.0, x=-20, y=20, anchor="ne", width=50, height=50)
        
        # Card Content
        content = ttk.Frame(main_frame, style="Card.TFrame", padding=50)
        content.place(relx=0.5, rely=0.5, anchor="center")

        # Header
        ttk.Label(content, text="SMART POS", style="Brand.TLabel", 
                  background="white", foreground=config.THEME_COLOR).pack(pady=(0, 15))
        
        ttk.Label(content, text="Enter Access PIN", style="Card.TLabel", 
                  foreground="#7f8c8d").pack(pady=(0, 25))

        # PIN Entry
        self.pin_var = tk.StringVar()
        self.entry = ttk.Entry(content, textvariable=self.pin_var, show="•", 
                              font=("Arial", 36), justify="center", width=8, style="TEntry")
        self.entry.pack(pady=(0, 30), ipady=15)
        self.entry.focus()

        # Numpad Container
        btn_frame = tk.Frame(content, bg="white")
        btn_frame.pack()

        keys = ['1', '2', '3', '4', '5', '6', '7', '8', '9', 'C', '0', 'GO']
        r, c = 0, 0
        
        for key in keys:
            # Button Logic
            if key == 'GO':
                bg_color = config.ACCENT_COLOR
                fg_color = "white"
                cmd = self.login
                relief = "flat"
            elif key == 'C':
                bg_color = config.WARNING_COLOR
                fg_color = "white"
                cmd = self.clear
                relief = "flat"
            else:
                bg_color = "#ecf0f1"
                fg_color = "#2c3e50"
                cmd = lambda k=key: self.press(k)
                relief = "flat"

            btn = tk.Button(btn_frame, text=key, font=("Segoe UI", 18, "bold"), 
                            width=6, height=2, bg=bg_color, fg=fg_color, 
                            relief=relief, activebackground="#bdc3c7",
                            command=cmd, borderwidth=0)
            
            btn.grid(row=r, column=c, padx=10, pady=10)
            c += 1
            if c > 2:
                c = 0
                r += 1

    def press(self, key):
        if len(self.pin_var.get()) < 4:
            self.entry.insert(tk.END, key)

    def clear(self):
        self.entry.delete(0, tk.END)

    def show_invalid_pin_popup(self):
        popup = tk.Toplevel(self.root)
        popup.overrideredirect(True)
        popup.transient(self.root)
        popup.attributes("-topmost", True)

        self.root.update_idletasks()
        popup_w, popup_h = 420, 230
        x = self.root.winfo_x() + (self.root.winfo_width() - popup_w) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - popup_h) // 2
        popup.geometry(f"{popup_w}x{popup_h}+{x}+{y}")
        popup.configure(bg=config.THEME_COLOR)

        card = tk.Frame(popup, bg="white")
        card.pack(fill=tk.BOTH, expand=True, padx=3, pady=3)

        header = tk.Frame(card, bg=config.DANGER_COLOR, pady=16)
        header.pack(fill=tk.X)
        tk.Label(header, text="INVALID PIN", font=("Segoe UI", 16, "bold"),
                 bg=config.DANGER_COLOR, fg="white").pack()

        body = tk.Frame(card, bg="white")
        body.pack(fill=tk.BOTH, expand=True)

        tk.Label(body, text="The PIN you entered is incorrect.",
                 font=("Segoe UI", 12, "bold"),
                 bg="white", fg=config.THEME_COLOR).pack(pady=(24, 6))
        tk.Label(body, text="Please try again.",
                 font=("Segoe UI", 11),
                 bg="white", fg="#7f8c8d").pack()

        def close_popup(event=None):
            popup.destroy()

        tk.Button(body, text="TRY AGAIN", font=("Segoe UI", 12, "bold"),
                  bg=config.DANGER_COLOR, fg="white", relief="flat",
                  activebackground="#e74c3c", activeforeground="white",
                  padx=22, pady=8, command=close_popup).pack(pady=(20, 0))

        popup.bind("<Return>", close_popup)
        popup.bind("<Escape>", close_popup)

        popup.grab_set()
        popup.focus_force()
        self.root.wait_window(popup)

    def login(self):
        pin = self.pin_var.get()
        user_info = self.db.get_user_by_pin(pin)
        if user_info:
            self.on_login_success(user_info)
        else:
            self.show_invalid_pin_popup()
            self.clear()
            self.entry.focus_set()

