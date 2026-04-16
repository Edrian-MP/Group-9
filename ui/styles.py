import tkinter as tk
from tkinter import ttk
from config import THEME_COLOR, ACCENT_COLOR, TEXT_COLOR, FONT_MAIN

# Enhanced Color Palette
BG_COLOR = "#f4f6f9"        # Light Grey/Blue background for the app
CARD_COLOR = "#ffffff"      # White for content areas
PRIMARY_COLOR = "#2c3e50"   # Deep Blue (THEME_COLOR)
SUCCESS_COLOR = "#27ae60"   # Green
WARNING_COLOR = "#e67e22"   # Orange
DANGER_COLOR = "#c0392b"    # Red
TEXT_DARK = "#2c3e50"
TEXT_LIGHT = "#ecf0f1"
BORDER_COLOR = "#dcdde1"

def apply_styles(root):
    style = ttk.Style()
    style.theme_use('clam')  # 'clam' supports widespread customization

    # Note: Root background must be set manually in main.py, 
    # but we configure frames here.
    
    # Main app background
    style.configure("Main.TFrame", background=BG_COLOR)
    
    # Content Cards (White with subtle border)
    style.configure("Card.TFrame", 
                    background=CARD_COLOR, 
                    relief="solid", 
                    borderwidth=1,
                    bordercolor=BORDER_COLOR)

    # Sidebar/Header backgrounds
    style.configure("Brand.TFrame", background=PRIMARY_COLOR)

    # Primary Action
    style.configure("Primary.TButton", 
                    font=("Segoe UI", 12, "bold"), 
                    background=ACCENT_COLOR, 
                    foreground="white", 
                    borderwidth=0, 
                    padding=10)
    style.map("Primary.TButton", 
              background=[('active', '#2980b9'), ('pressed', '#1f618d')])

    # Danger/Cancel Action
    style.configure("Danger.TButton", 
                    font=("Segoe UI", 11, "bold"), 
                    background=DANGER_COLOR, 
                    foreground="white", 
                    borderwidth=0,
                    padding=10)
    style.map("Danger.TButton", 
              background=[('active', '#e74c3c')])

    # Standard/Neutral Action
    style.configure("Secondary.TButton",
                    font=("Segoe UI", 11),
                    background="white",
                    foreground=TEXT_DARK,
                    borderwidth=1,
                    relief="solid",
                    bordercolor=BORDER_COLOR)
    style.map("Secondary.TButton",
              background=[('active', '#ecf0f1')])

    style.configure("Header.TLabel", 
                    background=BG_COLOR, 
                    foreground=TEXT_DARK, 
                    font=("Segoe UI", 24, "bold"))
    
    style.configure("SubHeader.TLabel", 
                    background=BG_COLOR, 
                    foreground=TEXT_DARK, 
                    font=("Segoe UI", 16, "bold"))

    style.configure("Body.TLabel", 
                    background=BG_COLOR, 
                    foreground=TEXT_DARK, 
                    font=("Segoe UI", 12))
    
    # Labels inside Cards need white background
    style.configure("Card.TLabel",
                    background=CARD_COLOR,
                    foreground=TEXT_DARK,
                    font=("Segoe UI", 12))

    style.configure("Brand.TLabel",
                    background=PRIMARY_COLOR,
                    foreground="white",
                    font=("Segoe UI", 20, "bold"))

    style.configure("Treeview",
                    background="white",
                    fieldbackground="white",
                    foreground=TEXT_DARK,
                    font=("Segoe UI", 12),
                    rowheight=35,  # Taller rows for touch/readability
                    borderwidth=0)
    
    style.configure("Treeview.Heading",
                    background="#bdc3c7",
                    foreground=TEXT_DARK,
                    font=("Segoe UI", 11, "bold"),
                    padding=10,
                    relief="flat")
    
    style.map("Treeview", 
              background=[('selected', ACCENT_COLOR)], 
              foreground=[('selected', 'white')])

    style.configure("TEntry", 
                    padding=10, 
                    relief="flat", 
                    borderwidth=1,
                    fieldbackground="white")
