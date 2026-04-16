import tkinter as tk
import sys
import logging
import os
import socket
import subprocess
import config
from urllib.parse import urlparse
from ui.styles import apply_styles
from ui.login_window import LoginWindow
from ui.seller_pos import SellerPOS
from ui.admin_dashboard import AdminDashboard
from ui.customer_display import CustomerDisplay
from modules.ai_engine import AIEngine
from modules.db_manager import DatabaseManager
from modules.cloud_sync import CloudSyncWorker
from drivers.camera_driver import CameraSystem
from drivers.scale_driver import SmartScale
from drivers.printer_driver import InvoicePrinter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

class SmartPOSApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Smart POS System")
        self.current_user = None
        self.local_receiver_process = None
        
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        self.root.geometry(f"{screen_w}x{screen_h}+0+0")
        
        self.root.attributes('-fullscreen', True)
        
        self.root.bind("<Escape>", lambda event: self.root.attributes("-fullscreen", False))
        self.root.lift()
        self.root.attributes('-topmost', True)
        self.root.after(1000, lambda: self.root.attributes('-topmost', False))
        
        apply_styles(self.root)
        self.root.configure(bg="#f4f6f9")

        self.root.config(cursor="none")
        _orig_tl_init = tk.Toplevel.__init__
        def _tl_no_cursor(self_tl, *a, **kw):
            _orig_tl_init(self_tl, *a, **kw)
            try: self_tl.config(cursor="none")
            except Exception: pass
        tk.Toplevel.__init__ = _tl_no_cursor
        
        self.db = DatabaseManager()
        self.cloud_sync = CloudSyncWorker(
            db_path=config.DB_PATH,
            endpoint=config.CLOUD_SYNC_ENDPOINT,
            api_key=config.CLOUD_SYNC_API_KEY,
            enabled=config.CLOUD_SYNC_ENABLED,
            interval_seconds=config.CLOUD_SYNC_INTERVAL_SECONDS,
            timeout_seconds=config.CLOUD_SYNC_TIMEOUT_SECONDS,
            batch_size=config.CLOUD_SYNC_BATCH_SIZE,
            max_retries=config.CLOUD_SYNC_MAX_RETRIES,
        )
        self.root.cloud_sync = self.cloud_sync
        self.cloud_sync.start()

        self.camera = CameraSystem()
        self.ai_engine = AIEngine()
        if hasattr(self.ai_engine, "get_runtime_status") and callable(self.ai_engine.get_runtime_status):
            try:
                ai_status = self.ai_engine.get_runtime_status()
                if not ai_status.get("feature_extractor_ready", False):
                    logging.error("AI disabled at startup: %s", ai_status.get("model_error"))
                elif int(ai_status.get("profiles_loaded", 0)) <= 0:
                    logging.warning("AI started without recognition profiles. Train products in Admin > Training.")
            except Exception as e:
                logging.warning("Could not read AI startup status: %s", e)
        self.scale = SmartScale(port='/dev/ttyUSB0')
        self.printer = InvoicePrinter()

        self.root.protocol("WM_DELETE_WINDOW", self.shutdown)

        self.customer_display = CustomerDisplay(self.root)
        self.root.customer_display = self.customer_display

        self.show_login()

    def _is_port_open(self, host, port):
        try:
            with socket.create_connection((host, int(port)), timeout=1.0):
                return True
        except OSError:
            return False

    def _should_auto_start_local_receiver(self):
        if not config.CLOUD_SYNC_ENABLED:
            return False
        if not bool(getattr(config, "CLOUD_AUTO_START_LOCAL_RECEIVER", True)):
            return False

        endpoint = str(config.CLOUD_SYNC_ENDPOINT or "").strip()
        if not endpoint:
            return False

        parsed = urlparse(endpoint)
        host = (parsed.hostname or "").strip().lower()
        return host in {"127.0.0.1", "localhost"}

    def _maybe_start_local_cloud_receiver(self):
        if not self._should_auto_start_local_receiver():
            return

        host = str(getattr(config, "CLOUD_LOCAL_RECEIVER_HOST", "127.0.0.1") or "127.0.0.1")
        port = int(getattr(config, "CLOUD_LOCAL_RECEIVER_PORT", 8080) or 8080)
        if self._is_port_open(host, port):
            logging.info("Cloud receiver already running at %s:%s", host, port)
            return

        command = [
            sys.executable,
            "-m",
            "uvicorn",
            "cloud_sync_server.app:app",
            "--host",
            host,
            "--port",
            str(port),
        ]
        try:
            self.local_receiver_process = subprocess.Popen(
                command,
                cwd=config.BASE_DIR,
                env=dict(os.environ),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logging.info("Started local cloud receiver on %s:%s", host, port)
        except Exception as e:
            self.local_receiver_process = None
            logging.warning("Could not auto-start local cloud receiver: %s", e)

    def show_login(self):
        self.clear_frame()
        self.current_user = None
        if hasattr(self, 'customer_display'):
            self.customer_display.show_idle()
        LoginWindow(self.root, self.db, self.on_login_success, self.shutdown)

    def on_login_success(self, user_info):
        self.clear_frame()
        self.current_user = user_info or {}
        role = self.current_user.get("role")
        if role == "Owner":
            self.customer_display.show_idle()
            AdminDashboard(
                self.root,
                self.db,
                self.camera,
                self.show_login,
                ai_engine=self.ai_engine,
                scale=self.scale
            )
        else:
            self.customer_display.show_selling()
            SellerPOS(
                self.root,
                self.db,
                self.camera,
                self.scale,
                self.printer,
                self.show_login,
                current_user=self.current_user,
                ai_engine=self.ai_engine
            )

    def clear_frame(self):
        for widget in self.root.winfo_children():
            if not isinstance(widget, tk.Toplevel):
                widget.destroy()

    def shutdown(self):
        try:
            if hasattr(self, 'cloud_sync') and self.cloud_sync is not None:
                self.cloud_sync.stop()
        except Exception as e:
            logging.warning("Cloud sync stop failed: %s", e)

        try:
            if self.local_receiver_process is not None and self.local_receiver_process.poll() is None:
                self.local_receiver_process.terminate()
        except Exception as e:
            logging.warning("Local receiver stop failed: %s", e)

        self.root.destroy()
        sys.exit()

    def run(self):
        try:
            self.root.mainloop()
        finally:
            try:
                if hasattr(self, 'cloud_sync') and self.cloud_sync is not None:
                    self.cloud_sync.stop()
            except Exception as e:
                logging.warning("Cloud sync stop on exit failed: %s", e)

            try:
                if self.local_receiver_process is not None and self.local_receiver_process.poll() is None:
                    self.local_receiver_process.terminate()
            except Exception as e:
                logging.warning("Local receiver stop on exit failed: %s", e)

if __name__ == "__main__":
    app = SmartPOSApp()
    app.run()

