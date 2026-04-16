import tkinter as tk
import config

_BG       = "#2c3e50"
_KEY_REG  = "#ecf0f1"
_KEY_SPEC = "#bdc3c7"
_KEY_FG   = "#2c3e50"
_HOVER    = "#d5d8dc"


def _make_key(parent, text, command, width=1, bg=_KEY_REG):
    btn = tk.Button(
        parent, text=text,
        font=("Segoe UI", 13, "bold"),
        bg=bg, fg=_KEY_FG,
        activebackground=_HOVER,
        relief="raised", bd=1,
        command=command,
    )
    return btn


class VirtualKeyboard(tk.Toplevel):

    def __init__(self, parent):
        super().__init__(parent)
        self.overrideredirect(True)
        self.configure(bg=_BG)
        self.transient(parent)
        self.attributes('-topmost', True)

        self.active_entry = None
        self.is_upper = True
        self._letter_buttons = []

        self.update_idletasks()
        sw = config.SCREEN_MAIN_W
        sh = config.SCREEN_MAIN_H
        kh = 300
        self.geometry(f"{sw}x{kh}+0+{sh - kh - config.TASKBAR_H}")

        self._build_rows(sw)

    def _build_rows(self, sw):
        PAD = 4
        outer = tk.Frame(self, bg=_BG, padx=PAD, pady=PAD)
        outer.pack(fill=tk.BOTH, expand=True)

        row0_keys = ['1','2','3','4','5','6','7','8','9','0']
        r0 = self._row_frame(outer)
        for k in row0_keys:
            b = _make_key(r0, k, lambda ch=k: self._press(ch))
            b.pack(side=tk.LEFT, expand=True, fill=tk.BOTH, padx=2, pady=2)
        bs = _make_key(r0, "⌫ Back", lambda: self._press('Back'), bg=_KEY_SPEC)
        bs.pack(side=tk.LEFT, expand=False, fill=tk.BOTH, padx=2, pady=2, ipadx=18)

        row1_keys = ['Q','W','E','R','T','Y','U','I','O','P']
        r1 = self._row_frame(outer)
        tk.Frame(r1, bg=_BG, width=24).pack(side=tk.LEFT)
        for k in row1_keys:
            b = _make_key(r1, k, lambda ch=k: self._press(ch))
            b.pack(side=tk.LEFT, expand=True, fill=tk.BOTH, padx=2, pady=2)
            self._letter_buttons.append((b, k.lower()))

        row2_keys = ['A','S','D','F','G','H','J','K','L']
        r2 = self._row_frame(outer)
        caps = _make_key(r2, "Caps", lambda: self._press('Caps'), bg=_KEY_SPEC)
        caps.pack(side=tk.LEFT, expand=False, fill=tk.BOTH, padx=2, pady=2, ipadx=14)
        for k in row2_keys:
            b = _make_key(r2, k, lambda ch=k: self._press(ch))
            b.pack(side=tk.LEFT, expand=True, fill=tk.BOTH, padx=2, pady=2)
            self._letter_buttons.append((b, k.lower()))
        enter = _make_key(r2, "Enter ↵", lambda: self._press('ENTER'), bg=_KEY_SPEC)
        enter.pack(side=tk.LEFT, expand=False, fill=tk.BOTH, padx=2, pady=2, ipadx=18)

        row3_keys = ['Z','X','C','V','B','N','M']
        r3 = self._row_frame(outer)
        for k in row3_keys:
            b = _make_key(r3, k, lambda ch=k: self._press(ch))
            b.pack(side=tk.LEFT, expand=True, fill=tk.BOTH, padx=2, pady=2)
            self._letter_buttons.append((b, k.lower()))
        for sym in ['-', '_', '.']:
            b2 = _make_key(r3, sym, lambda ch=sym: self._press(ch))
            b2.pack(side=tk.LEFT, expand=True, fill=tk.BOTH, padx=2, pady=2)

        r4 = self._row_frame(outer)
        clr = _make_key(r4, "Clear", lambda: self._press('Clear'), bg=_KEY_SPEC)
        clr.pack(side=tk.LEFT, expand=False, fill=tk.BOTH, padx=2, pady=2, ipadx=10)
        space = _make_key(r4, "Space", lambda: self._press('Space'), bg=_KEY_SPEC)
        space.pack(side=tk.LEFT, expand=True, fill=tk.BOTH, padx=2, pady=2)
        close_btn = _make_key(r4, "⬇  Hide", lambda: self.withdraw(), bg="#27ae60")
        close_btn.config(fg="white", activebackground="#2ecc71")
        close_btn.pack(side=tk.LEFT, expand=False, fill=tk.BOTH, padx=2, pady=2, ipadx=14)


    def _row_frame(self, parent):
        f = tk.Frame(parent, bg=_BG)
        f.pack(side=tk.TOP, fill=tk.BOTH, expand=True, pady=1)
        return f
    def set_target(self, entry_widget):
        self.active_entry = entry_widget

    def toggle_caps(self):
        self.is_upper = not self.is_upper
        for btn, base in self._letter_buttons:
            btn.config(text=base.upper() if self.is_upper else base)

    def _press(self, key):
        if not self.active_entry:
            return
        if key == 'Caps':
            self.toggle_caps()
        elif key == 'Back':
            cur = self.active_entry.get()
            new_val = cur[:-1]
            self.active_entry.delete(0, tk.END)
            self.active_entry.insert(0, new_val)
            if not new_val:
                self.withdraw()
        elif key == 'Space':
            self.active_entry.insert(tk.END, ' ')
        elif key == 'Clear':
            self.active_entry.delete(0, tk.END)
        elif key == 'ENTER':
            self.withdraw()
        else:
            char = key
            if len(key) == 1 and key.isalpha():
                char = key.upper() if self.is_upper else key.lower()
            self.active_entry.insert(tk.END, char)

    def press(self, key):
        self._press(key)

