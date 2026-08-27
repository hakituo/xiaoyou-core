import webview
import threading
import sys
import os
import multiprocessing
import time

# Global state
server_started = threading.Event()
current_window = None


class WindowAPI:
    """API exposed to JavaScript"""

    def __init__(self):
        self.window = None

    def set_window(self, window):
        self.window = window

    def switch_to_pet_mode(self):
        """Switch to transparent desktop pet mode"""
        print("Switching to Pet Mode...")
        if self.window:
            # First, update the URL (Frontend should handle transparency via CSS)
            self.window.load_url("http://127.0.0.1:8000/#pet-mode")

            # Wait a brief moment for the page to signal it's ready or just delay resize
            # Resizing too early might cause white flash or crash if renderer is busy
            # However, in pywebview API, these are synchronous-ish but we can't sleep here easily without blocking UI.
            # We will resize.

            # IMPORTANT: For transparency to work on Windows, the window size change might trigger repaint.
            self.window.resize(350, 500)
            self.window.on_top = True  # Force on top

            # Additional trick: Trigger a repaint or style update if possible?
            # Actually, simply loading #pet-mode should trigger the CSS `background: transparent`.

    def switch_to_main_mode(self):
        """Switch back to main window mode"""
        print("Switching to Main Mode...")
        if self.window:
            self.window.load_url("http://127.0.0.1:8000/")
            self.window.resize(1280, 800)
            self.window.on_top = False


class WindowManager:
    def __init__(self):
        self.api = WindowAPI()
        self.window = None
        self.server_process = None
        # 从配置读取端口
        try:
            from config.integrated_config import get_settings
            self.port = get_settings().server.port
        except Exception:
            self.port = 8000

    def start(self):
        # Start backend in a separate PROCESS to avoid GIL issues
        self.server_process = multiprocessing.Process(target=start_server)
        self.server_process.start()

        # Wait for server to start (with timeout)
        # Since it's a separate process, we can't share the Event directly unless we use a Manager,
        # but for simplicity, we'll just check the port or sleep briefly.
        print("Waiting for server to start...")
        self._wait_for_server(port=self.port, timeout=15)

        if not self.server_process.is_alive():
            print("CRITICAL ERROR: Server process died unexpectedly!")
            # We can't easily show a UI alert here before webview starts,
            # but we can try to start webview with an error page or similar.
            # For now, let's just proceed, but the logging above will capture the error.
        else:
            print("Server check complete.")

        url = f"http://127.0.0.1:{self.port}/"

        self.window = webview.create_window(
            "Xiaoyou Core",
            url,
            width=1280,
            height=800,
            resizable=True,
            min_size=(800, 600),
            confirm_close=True,
            transparent=True,
            frameless=True,
            on_top=False,
            js_api=self.api,
        )
        self.api.set_window(self.window)

        self.window.events.closing += self.on_closing

        webview.start(debug=True, gui="edgechromium")

    def _wait_for_server(self, host="127.0.0.1", port=8000, timeout=10):
        import socket

        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                with socket.create_connection((host, port), timeout=1):
                    return True
            except (OSError, ConnectionRefusedError):
                time.sleep(0.5)
        print("Warning: Server wait timeout, proceeding anyway...")
        return False

    def on_closing(self):
        print("Application closing, terminating server...")
        if self.server_process and self.server_process.is_alive():
            self.server_process.terminate()
            self.server_process.join(timeout=2)
        return True


def start_server():
    """Start the FastAPI server"""
    # Setup logging to file for debugging
    import logging

    # 调试日志受 config.debug_config.server_debug 控制，默认关闭，避免长期堆积；
    # 文件统一写入 logs/ 目录，而非根目录/exe 目录。
    _server_debug_enabled = False
    try:
        from config.debug_config import is_debug_enabled
        _server_debug_enabled = is_debug_enabled("server_debug")
    except Exception:
        _server_debug_enabled = False

    if _server_debug_enabled:
        # logs 目录：优先用项目根目录下的 logs/，打包后回退到 exe 同级 logs/
        _base = (
            os.path.dirname(sys.executable)
            if getattr(sys, "frozen", False)
            else os.path.dirname(os.path.abspath(__file__))
        )
        _logs_dir = os.path.join(_base, "logs")
        os.makedirs(_logs_dir, exist_ok=True)
        log_file = os.path.join(_logs_dir, "server_debug.log")
        logging.basicConfig(
            filename=log_file,
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )
        logger = logging.getLogger("DesktopServer")
        logger.info("Server process starting (debug log enabled)...")

    # Re-import needed modules in new process
    try:
        import uvicorn
        from main import app as fastapi_app

        logger.info("Modules imported successfully")

        # 从配置读取端口
        try:
            from config.integrated_config import get_settings
            port = get_settings().server.port
        except Exception:
            port = 8000

        config_kwargs = {
            "host": "127.0.0.1",
            "port": port,
            "log_level": "info",
            "workers": 1,
        }

        if getattr(sys, "frozen", False):
            config_kwargs["log_level"] = "error"
            config_kwargs["reload"] = False

        logger.info(f"Starting uvicorn with config: {config_kwargs}")

        # IMPORTANT: Run uvicorn programmatically with Config/Server to avoid signal issues
        config = uvicorn.Config(fastapi_app, **config_kwargs)
        server = uvicorn.Server(config)

        # Override install_signal_handlers
        server.install_signal_handlers = lambda: None

        server.run()
    except Exception as e:
        error_msg = f"Server error: {e}"
        print(error_msg)
        logger.critical(error_msg, exc_info=True)


def main():
    multiprocessing.freeze_support()
    window_manager = WindowManager()
    window_manager.start()


if __name__ == "__main__":
    main()
