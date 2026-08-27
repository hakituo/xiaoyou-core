import tkinter as tk
from tkinter import ttk, scrolledtext
import subprocess
import threading
import sys
import os
import json
import time
import socket
import multiprocessing
import signal
import webbrowser
from PIL import Image, ImageDraw
import pystray
from pystray import MenuItem as item

# Configuration File
CONFIG_FILE = "launcher_config.json"
DEFAULT_CONFIG = {
    "backend_cmd": r"venv_core\Scripts\python.exe main.py",
    "backend_cwd": ".",
    "frontend_cmd": "npm run dev",
    "frontend_cwd": "./clients/frontend/Aveline_UI",
    "auto_start": False,
    "minimize_to_tray_on_close": True,
}


def run_internal_backend():
    """Runs the backend server directly within this process."""
    # Ensure current directory is correct for relative imports
    if getattr(sys, "frozen", False):
        os.chdir(os.path.dirname(sys.executable))

    try:
        import uvicorn

        # Import main module.
        # Note: In frozen app, main needs to be importable.
        import main

        # 从配置读取端口
        try:
            from config.integrated_config import get_settings
            port = get_settings().server.port
        except Exception:
            port = 8000

        # Override config to disable reload
        uvicorn.run(main.app, host="0.0.0.0", port=port, log_level="info")
    except Exception:
        # Write to a log file since stdout might not be visible
        with open("backend_error.log", "w") as f:
            import traceback

            traceback.print_exc(file=f)
        sys.exit(1)


class LauncherApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Xiaoyou Core Launcher")
        self.root.geometry("600x450")

        # Load Config
        self.config = self.load_config()

        # State
        self.backend_process = None
        self.frontend_process = None
        self.is_running = False
        self.tray_icon = None

        # UI Setup
        self.create_widgets()

        # Tray Setup
        self.setup_tray()

        # Protocol Handlers
        self.root.protocol("WM_DELETE_WINDOW", self.on_close_window)

        # Auto Start
        if self.config.get("auto_start"):
            self.root.after(1000, self.start_services)

    def load_config(self):
        # Adjust defaults if frozen
        if getattr(sys, "frozen", False):
            # If frozen, default backend is self with --worker
            # default frontend is browser
            defaults = {
                "backend_cmd": f'"{sys.executable}" --worker',
                "backend_cwd": ".",
                "frontend_cmd": "http://localhost:8000",
                "frontend_cwd": ".",
                "auto_start": False,
                "minimize_to_tray_on_close": True,
            }
        else:
            defaults = DEFAULT_CONFIG.copy()

        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    user_config = json.load(f)
                    # Merge with defaults to ensure all keys exist
                    for k, v in defaults.items():
                        if k not in user_config:
                            user_config[k] = v
                    return user_config
            except Exception:
                pass
        return defaults

    def save_config(self):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(self.config, f, indent=4)

    def create_widgets(self):
        # Status Frame
        status_frame = ttk.LabelFrame(self.root, text="Service Status")
        status_frame.pack(fill="x", padx=10, pady=5)

        self.status_label = ttk.Label(status_frame, text="Stopped", foreground="red")
        self.status_label.pack(side="left", padx=5, pady=5)

        self.progress = ttk.Progressbar(status_frame, mode="indeterminate")
        self.progress.pack(side="right", fill="x", expand=True, padx=5, pady=5)

        # Controls Frame
        ctrl_frame = ttk.Frame(self.root)
        ctrl_frame.pack(fill="x", padx=10, pady=5)

        self.start_btn = ttk.Button(
            ctrl_frame, text="Start Services", command=self.start_services
        )
        self.start_btn.pack(side="left", padx=5)

        self.stop_btn = ttk.Button(
            ctrl_frame,
            text="Stop Services",
            command=self.stop_services,
            state="disabled",
        )
        self.stop_btn.pack(side="left", padx=5)

        self.restart_btn = ttk.Button(
            ctrl_frame, text="Restart", command=self.restart_services, state="disabled"
        )
        self.restart_btn.pack(side="left", padx=5)

        settings_btn = ttk.Button(
            ctrl_frame, text="Settings", command=self.open_settings
        )
        settings_btn.pack(side="right", padx=5)

        # Log Area
        log_frame = ttk.LabelFrame(self.root, text="Logs")
        log_frame.pack(fill="both", expand=True, padx=10, pady=5)

        self.log_area = scrolledtext.ScrolledText(
            log_frame, state="disabled", height=10
        )
        self.log_area.pack(fill="both", expand=True, padx=5, pady=5)

    def log(self, message):
        timestamp = time.strftime("%H:%M:%S")
        self.log_area.config(state="normal")
        self.log_area.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_area.see(tk.END)
        self.log_area.config(state="disabled")

    def create_image(self):
        # Generate a simple icon
        width = 64
        height = 64
        color1 = "blue"
        color2 = "white"
        image = Image.new("RGB", (width, height), color1)
        dc = ImageDraw.Draw(image)
        dc.rectangle(
            (width // 4, height // 4, width * 3 // 4, height * 3 // 4), fill=color2
        )
        return image

    def setup_tray(self):
        image = self.create_image()
        menu = pystray.Menu(
            item("Show", self.show_window),
            item("Stop Services", self.stop_services),
            item("Exit", self.quit_app),
        )
        self.tray_icon = pystray.Icon("name", image, "Xiaoyou Launcher", menu)

    def show_window(self, icon=None, item=None):
        self.root.after(0, self.root.deiconify)

    def run_tray(self):
        self.tray_icon.run()

    def on_close_window(self):
        if self.config.get("minimize_to_tray_on_close", True):
            self.root.withdraw()
            if not self.tray_icon.visible:
                threading.Thread(target=self.run_tray, daemon=True).start()
        else:
            self.confirm_quit()

    def confirm_quit(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Confirm Exit")
        dialog.geometry("300x150")
        dialog.transient(self.root)
        dialog.grab_set()

        ttk.Label(dialog, text="What do you want to do?").pack(pady=10)

        def close_all():
            self.stop_services()
            self.root.quit()
            # self.tray_icon.stop() # If running
            sys.exit(0)

        def min_tray():
            dialog.destroy()
            self.root.withdraw()
            if not self.tray_icon.visible:
                threading.Thread(target=self.run_tray, daemon=True).start()

        def cancel():
            dialog.destroy()

        ttk.Button(
            dialog, text="Close All (Terminate Processes)", command=close_all
        ).pack(fill="x", padx=20, pady=2)
        ttk.Button(dialog, text="Minimize to Tray", command=min_tray).pack(
            fill="x", padx=20, pady=2
        )
        ttk.Button(dialog, text="Cancel", command=cancel).pack(
            fill="x", padx=20, pady=2
        )

    def quit_app(self, icon=None, item=None):
        self.root.after(0, self.confirm_quit_tray)

    def confirm_quit_tray(self):
        self.stop_services()
        self.tray_icon.stop()
        self.root.quit()
        sys.exit(0)

    def start_services(self):
        if self.is_running:
            return

        self.is_running = True
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.restart_btn.config(state="normal")
        self.status_label.config(text="Starting...", foreground="orange")
        self.progress.start()

        threading.Thread(target=self._start_sequence, daemon=True).start()

    def _start_sequence(self):
        # Start Backend
        backend_cmd = self.config["backend_cmd"]
        backend_cwd = self.config["backend_cwd"]

        self.log(f"Starting Backend: {backend_cmd}")
        try:
            # Shell=True for windows to avoid path issues, but be careful with security
            backend_popen_kwargs = {
                "cwd": os.path.abspath(backend_cwd),
                "shell": True,
            }
            if os.name == "nt":
                backend_popen_kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
            else:
                backend_popen_kwargs["start_new_session"] = True

            self.backend_process = subprocess.Popen(backend_cmd, **backend_popen_kwargs)
            self.log("Backend process launched.")
        except Exception as e:
            self.log(f"Error starting backend: {e}")
            self.stop_services_thread_safe()
            return

        # 直接扫描默认端口范围，避免依赖额外的端口文件。
        self.log("Waiting for backend port...")
        target_port = 8000
        candidate_ports = list(range(8000, 8050))
        start_wait = time.time()
        found = False
        while time.time() - start_wait < 30:
            for candidate_port in candidate_ports:
                if self.wait_for_port(candidate_port, timeout=0.2):
                    target_port = candidate_port
                    found = True
                    break
            if found:
                break

            time.sleep(1)

        if found:
            self.log(f"Backend is ready on port {target_port}.")
        else:
            self.log("Backend startup timed out. Continuing anyway...")

        # Start Frontend
        frontend_cmd = self.config["frontend_cmd"]
        frontend_cwd = self.config["frontend_cwd"]

        self.log(f"Starting Frontend: {frontend_cmd}")
        try:
            frontend_cmd_stripped = frontend_cmd.strip()
            url = ""
            if frontend_cmd_stripped.startswith(("http://", "https://")):
                url = frontend_cmd_stripped
            elif (
                frontend_cmd_stripped.lower().startswith("start ")
                and "http" in frontend_cmd_stripped.lower()
            ):
                url = frontend_cmd_stripped.split(None, 1)[1].strip()
            elif (
                frontend_cmd_stripped.lower().startswith("xdg-open ")
                and "http" in frontend_cmd_stripped.lower()
            ):
                url = frontend_cmd_stripped.split(None, 1)[1].strip()

            if url:
                webbrowser.open(url)
                self.frontend_process = None
                self.log("Frontend opened in default browser.")
            else:
                frontend_popen_kwargs = {
                    "cwd": os.path.abspath(frontend_cwd),
                    "shell": True,
                }
                if os.name == "nt":
                    frontend_popen_kwargs["creationflags"] = (
                        subprocess.CREATE_NEW_CONSOLE
                    )
                else:
                    frontend_popen_kwargs["start_new_session"] = True

                self.frontend_process = subprocess.Popen(
                    frontend_cmd, **frontend_popen_kwargs
                )
                self.log("Frontend process launched.")
        except Exception as e:
            self.log(f"Error starting frontend: {e}")

        self.root.after(0, self._update_running_ui)

        # Start Monitor
        threading.Thread(target=self.monitor_processes, daemon=True).start()

    def _update_running_ui(self):
        self.status_label.config(text="Running", foreground="green")
        self.progress.stop()

    def stop_services(self):
        threading.Thread(target=self._stop_sequence, daemon=True).start()

    def _stop_sequence(self):
        self.log("Stopping services...")
        if self.frontend_process:
            self.kill_process(self.frontend_process)
            self.frontend_process = None

        if self.backend_process:
            self.kill_process(self.backend_process)
            self.backend_process = None

        self.is_running = False
        self.root.after(0, self._update_stopped_ui)
        self.log("Services stopped.")

    def kill_process(self, process):
        try:
            if not process or process.poll() is not None:
                return

            import psutil

            try:
                parent = psutil.Process(process.pid)
                for child in parent.children(recursive=True):
                    child.kill()
                parent.kill()
            except psutil.NoSuchProcess:
                pass
            except Exception as e:
                self.log(f"Error killing process with psutil: {e}")
                # Fallback to standard kill
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )
                else:
                    try:
                        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                    except Exception:
                        process.kill()
        except Exception as e:
            self.log(f"Error killing process: {e}")

    def stop_services_thread_safe(self):
        self.root.after(0, self.stop_services)

    def _update_stopped_ui(self):
        self.status_label.config(text="Stopped", foreground="red")
        self.progress.stop()
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.restart_btn.config(state="disabled")

    def restart_services(self):
        self.stop_services()
        # Wait a bit
        self.root.after(2000, self.start_services)

    def wait_for_port(self, port, host="localhost", timeout=30):
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                connect_timeout = max(0.1, min(1.0, float(timeout)))
                with socket.create_connection((host, port), timeout=connect_timeout):
                    return True
            except OSError:
                remaining = timeout - (time.time() - start_time)
                if remaining <= 0:
                    break
                time.sleep(min(0.2, remaining))
        return False

    def monitor_processes(self):
        while self.is_running:
            if self.backend_process and self.backend_process.poll() is not None:
                self.log("Backend process exited unexpectedly.")
                self.backend_process = None
                # Optional: Restart

            if self.frontend_process and self.frontend_process.poll() is not None:
                self.log("Frontend process exited unexpectedly.")
                self.frontend_process = None

            time.sleep(5)

    def open_settings(self):
        SettingsDialog(self.root, self.config, self.save_config)


class SettingsDialog:
    def __init__(self, parent, config, save_callback):
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Settings")
        self.dialog.geometry("500x300")
        self.config = config
        self.save_callback = save_callback

        self.create_widgets()

    def create_widgets(self):
        # Backend
        ttk.Label(self.dialog, text="Backend Command:").pack(anchor="w", padx=10)
        self.backend_cmd = ttk.Entry(self.dialog)
        self.backend_cmd.insert(0, self.config["backend_cmd"])
        self.backend_cmd.pack(fill="x", padx=10, pady=2)

        ttk.Label(self.dialog, text="Backend CWD:").pack(anchor="w", padx=10)
        self.backend_cwd = ttk.Entry(self.dialog)
        self.backend_cwd.insert(0, self.config["backend_cwd"])
        self.backend_cwd.pack(fill="x", padx=10, pady=2)

        # Frontend
        ttk.Label(self.dialog, text="Frontend Command:").pack(anchor="w", padx=10)
        self.frontend_cmd = ttk.Entry(self.dialog)
        self.frontend_cmd.insert(0, self.config["frontend_cmd"])
        self.frontend_cmd.pack(fill="x", padx=10, pady=2)

        ttk.Label(self.dialog, text="Frontend CWD:").pack(anchor="w", padx=10)
        self.frontend_cwd = ttk.Entry(self.dialog)
        self.frontend_cwd.insert(0, self.config["frontend_cwd"])
        self.frontend_cwd.pack(fill="x", padx=10, pady=2)

        # Options
        self.auto_start = tk.BooleanVar(value=self.config["auto_start"])
        ttk.Checkbutton(
            self.dialog, text="Auto Start on Launch", variable=self.auto_start
        ).pack(anchor="w", padx=10, pady=5)

        self.min_tray = tk.BooleanVar(value=self.config["minimize_to_tray_on_close"])
        ttk.Checkbutton(
            self.dialog, text="Minimize to Tray on Close", variable=self.min_tray
        ).pack(anchor="w", padx=10, pady=5)

        # Buttons
        btn_frame = ttk.Frame(self.dialog)
        btn_frame.pack(fill="x", pady=10)
        ttk.Button(btn_frame, text="Save", command=self.save).pack(
            side="right", padx=10
        )
        ttk.Button(btn_frame, text="Cancel", command=self.dialog.destroy).pack(
            side="right", padx=10
        )

    def save(self):
        self.config["backend_cmd"] = self.backend_cmd.get()
        self.config["backend_cwd"] = self.backend_cwd.get()
        self.config["frontend_cmd"] = self.frontend_cmd.get()
        self.config["frontend_cwd"] = self.frontend_cwd.get()
        self.config["auto_start"] = self.auto_start.get()
        self.config["minimize_to_tray_on_close"] = self.min_tray.get()
        self.save_callback()
        self.dialog.destroy()


if __name__ == "__main__":
    multiprocessing.freeze_support()

    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        run_internal_backend()
    else:
        root = tk.Tk()
        app = LauncherApp(root)
        root.mainloop()
