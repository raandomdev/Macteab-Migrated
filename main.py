from __future__ import annotations

import traceback
import json
import threading
from typing import Optional, Any
import atexit
import subprocess
import webbrowser
import webview
import os
import sys
import time
import psutil
from datetime import datetime
import logging
import shutil
import urllib.request
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import socket
import random
from pathlib import Path
from biome_tracker.config import APPDATA_BASE
from biome_tracker.core import BiomeTracker
import keyboard


def _macos_accessibility_trusted() -> bool:
    if sys.platform != 'darwin':
        return True
    try:
        from ApplicationServices import AXIsProcessTrusted
        return bool(AXIsProcessTrusted())
    except Exception:
        return True  # pyobjc frameworks missing; fail open rather than block startup

def _macos_screen_capture_allowed() -> bool:
    if sys.platform != 'darwin':
        return True
    try:
        import Quartz
        if hasattr(Quartz, "CGPreflightScreenCaptureAccess"):
            return bool(Quartz.CGPreflightScreenCaptureAccess())
        return True
    except Exception:
        return True

def _print_macos_setup_hint() -> None:
    if sys.platform != 'darwin':
        return
    script_path = os.path.join(os.getcwd(), 'setup_macos_ocr.sh')
    if os.path.exists(script_path):
        print(f"[macOS setup] OCR dependencies can be installed with: {script_path}")

def prompt_macos_accessibility():
    if sys.platform != 'darwin':
        return {"success": True}
    try:
        from ApplicationServices import AXIsProcessTrustedWithOptions
        trusted = AXIsProcessTrustedWithOptions({"AXTrustedCheckOptionPrompt": True})
        return {"success": bool(trusted)}
    except Exception as e:
        return {"success": False, "error": str(e)}

def prompt_macos_screen_capture():
    if sys.platform != 'darwin':
        return {"success": True}
    try:
        import Quartz
        if hasattr(Quartz, "CGRequestScreenCaptureAccess"):
            Quartz.CGRequestScreenCaptureAccess()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}

def get_macos_permissions():
    return {
        "accessibility": _macos_accessibility_trusted(),
        "screen_capture": _macos_screen_capture_allowed(),
    }

_print_macos_setup_hint()
get_macos_permissions()

def install_homebrew_tesseract():
    if sys.platform != 'darwin':
        return 
    
    download_link = "https://raw.githubusercontent.com/raandomdev/Noteab-Macro/refs/heads/main/assets/setup_macos_ocr.sh"
    try:
        req = urllib.request.Request(download_link, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=8) as response:
            script_content = response.read().decode('utf-8')
            if script_content and len(script_content) > 100:
                script_path = os.path.join(os.getcwd(), 'setup_macos_ocr.sh')
                with open(script_path, "w", encoding="utf-8") as f:
                    f.write(script_content)
                os.chmod(script_path, 0o755)
                print(f"[macOS setup] Downloaded OCR setup script to: {script_path}")
                print(f"[macOS setup] You can run it with: bash {script_path}")
    except Exception as e:
        print(f"[macOS setup] Failed to download OCR setup script: {e}")

ORIGINAL_ABS_FILE = os.path.abspath(__file__)
os.environ['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'] = '--disable-gpu'

APPDATA_BASE.mkdir(parents=True, exist_ok=True)
os.chdir(APPDATA_BASE)

_lockfile_path = APPDATA_BASE / ".coteab_macro.lock"
try:
    if should_block_start(_lockfile_path):
        print("Coteab Macro is already running! Exiting.")
        sys.exit(0)

    clear_stale_lockfile(_lockfile_path)

    try:
        _lockfile_path.write_text(str(os.getpid()))
    except Exception:
        pass

    def _remove_lockfile():
        try:
            if _lockfile_path.exists():
                _lockfile_path.unlink()
        except Exception:
            pass
    atexit.register(_remove_lockfile)
except Exception:
    pass

try:
    import numpy
    import cv2
    import pyautogui
except Exception as e:
    err_text = str(e)
    if "numpy" in err_text.lower() or "c-extension" in err_text.lower() or "cv2" in err_text.lower() or "dll" in err_text.lower():
        print("Coteab Macro failed to load required Python packages:", err_text)
        print("Try installing dependencies: python3 -m pip install -r requirements.txt")
        sys.exit(1)
    else:
        raise


def _safe_screenshot(*args, **kwargs):
    if sys.platform == 'darwin' and not _macos_screen_capture_allowed():
        print('[Screenshot] macOS screen capture permission missing; skipping screenshot.')
        try:
            from PIL import Image
            return Image.new('RGB', (1, 1), color=(0, 0, 0))
        except Exception:
            return None
    return pyautogui._screenshot(*args, **kwargs)


if 'pyautogui' in globals() and hasattr(pyautogui, 'screenshot'):
    pyautogui._screenshot = pyautogui.screenshot
    pyautogui.screenshot = _safe_screenshot

# i added this so we can easily change macro version upon releases without having to change multiple back-end & front-end behaviours
# for future people that is reading the open source code, hello :p
current_version = "v2.1.8"
os.environ["COTEAB_MACRO_VERSION"] = current_version
UPDATE_LATEST_RELEASE_API_URL = "https://api.github.com/repos/raandomdev/Noteab-Macro/releases/latest"
os.environ["COTEAB_UPDATE_API_URL"] = UPDATE_LATEST_RELEASE_API_URL
os.environ["WEBKIT_DISABLE_COMPOSITING_MODE"] = "1" 

_wv2_user_data_base = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
    "CoteabMacro", "WebView2UserData"
)
try:
    if os.path.exists(_wv2_user_data_base):
        for _f in os.listdir(_wv2_user_data_base):
            try: shutil.rmtree(os.path.join(_wv2_user_data_base, _f), ignore_errors=True)
            except Exception: pass
except Exception:
    pass

_wv2_user_data = os.path.join(_wv2_user_data_base, f"Session_{int(time.time())}")
os.makedirs(_wv2_user_data, exist_ok=True)
os.environ["WEBVIEW2_USER_DATA_FOLDER"] = _wv2_user_data

try:
    if sys.platform == 'win32':
        psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    else:
        psutil.Process().nice(10)
except Exception: pass

from biome_tracker.config import (
    ensure_workspace_files,
    sync_config,
    load_config,
    save_config,
    normalize_auto_pop_biomes,
)
from biome_tracker.startup import clear_stale_lockfile, should_block_start

def get_base_path(): return sys._MEIPASS if hasattr(sys, '_MEIPASS') else os.path.dirname(ORIGINAL_ABS_FILE)

def _get_frontend_dist_dirs() -> list[str]:
    base_path = get_base_path()
    from biome_tracker.config import APPDATA_BASE
    
    dirs = [
        os.path.join(str(APPDATA_BASE), "dist"),
        os.path.join(str(APPDATA_BASE), "frontend", "dist"),
        os.path.join(os.getcwd(), "frontend", "dist"),
        os.path.join(os.getcwd(), "dist"),
    ]
    
    if getattr(sys, "frozen", False):
        dirs.append(os.path.join(base_path, "lib", "dist"))
        dirs.append(os.path.join(base_path, "dist"))
    else:
        dirs.append(os.path.join(base_path, "frontend", "dist"))
        dirs.append(os.path.join(base_path, "lib", "dist"))
        dirs.append(os.path.join(base_path, "dist"))

    return [d for d in dirs if os.path.exists(d)]


def get_frontend_entry():
    for dist_dir in _get_frontend_dist_dirs():
        index_file = os.path.join(dist_dir, "index.html")
        if os.path.exists(index_file):
            try:
                abs_path = os.path.abspath(index_file).replace("\\", "/")
                with open(index_file, "r", encoding="utf-8") as f:
                    html_content = f.read()
                print(f"Loading frontend from local: {abs_path}")
                return {"html": html_content, "url": f"file:///{abs_path}"}
            except Exception as e:
                print(f"Error reading local index.html: {e}")

    frontend_url = "https://raw.githubusercontent.com/raandomdev/Noteab-Macro/refs/heads/main/assets/index.html"
    try:
        from biome_tracker.config import APPDATA_BASE
        appdata_dist = os.path.join(str(APPDATA_BASE), "dist")
        os.makedirs(appdata_dist, exist_ok=True)

        req = urllib.request.Request(frontend_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=8) as response:
            html_content = response.read().decode('utf-8')
            if html_content and len(html_content) > 1000:
                saved_path = os.path.join(appdata_dist, "index.html")
                with open(saved_path, "w", encoding="utf-8") as f: f.write(html_content)
                abs_path = os.path.abspath(saved_path).replace("\\", "/")
                print(f"Fetched frontend from GitHub -> saved to: {abs_path}")
                return {"html": html_content, "url": f"file:///{abs_path}"}
    except Exception as e:
        print(f"Failed to fetch frontend from GitHub: {e}")

    return {"url": "http://localhost:5173"}



def _read_cli_value(flag, default=""):
    try:
        if flag not in sys.argv: return default
        idx = sys.argv.index(flag)
        if idx + 1 >= len(sys.argv): return default
        return str(sys.argv[idx + 1]).strip()
    except Exception:
        return default


def _cfg_bool(cfg, key, default=False):
    try:
        if not isinstance(cfg, dict): return bool(default)
        val = cfg.get(key, default)
        if isinstance(val, str):
            val = val.strip().lower()
            return val in ("1", "true", "yes", "on")
        return bool(val)
    except Exception:
        return bool(default)

class LoggerWriter:
    def __init__(self, filename="macro_logs.txt", original_stream=None):
        self.terminal = original_stream
        self.filename = filename

    def write(self, message):
        if self.terminal is not None:
            try:
                self.terminal.write(message)
                self.terminal.flush()
            except UnicodeEncodeError:
                try:
                    self.terminal.write(message.encode("ascii", "replace").decode("ascii"))
                    self.terminal.flush()
                except Exception:
                    pass
            except Exception:
                pass
        try:
            with open(self.filename, "a", encoding="utf-8") as f:
                f.write(message)
        except Exception:
            pass

    def flush(self):
        if self.terminal is not None:
            try:
                self.terminal.flush()
            except Exception:
                pass

sys.stdout = LoggerWriter("macro_logs.txt", sys.stdout)
sys.stderr = LoggerWriter("macro_logs.txt", sys.stderr)

class Api:
    def __init__(self, tracker=None):
        self._tracker = tracker
        self._window = None
        self._calib_mgr = None

        # fishing mode stuff
        self._fishing_stop_event = threading.Event()
        self._fishing_thread = None
        self._fishing_lock = threading.Lock()
        self._fishing_runtime_state = {
            "fish_caught_count": 0,
            "fish_caught_since_merchant": 0,
            "fish_caught_since_br_sc": 0,
            "rejoin_in_progress": False,
            "force_sell_on_next_cycle": False,
            "merchant_requires_reset": False,
        }

        # rare biome pop up confirmation
        self._biome_confirm_evt = threading.Event()
        self._biome_confirm_result = None
        self.emergency_port = None

    def set_window(self, window):
        self._window = window
        if self._calib_mgr is None:
            from biome_tracker.base_support import CalibrationManager
            self._calib_mgr = CalibrationManager()
        self._calib_mgr.set_refs(
            window=window,
            tracker=self._tracker,
            save_fn=save_config,
            emit_fn=self.emit_calibration_result
        )

    def get_config(self):
        t = self._tracker
        if t and isinstance(getattr(t, 'config', None), dict) and t.config:
            return t.config
        return load_config()

    def get_macos_permissions(self):
        return {"accessibility": True, "screen_capture": True}

    def prompt_macos_accessibility(self):
        return {"success": True}

    def prompt_macos_screen_capture(self):
        return {"success": True}

    def get_biome_data(self):
        if self._tracker and isinstance(getattr(self._tracker, "biome_data", None), dict):
            result = {}
            for biome, data in self._tracker.biome_data.items():
                color = data.get("color", "0xffffff")
                if isinstance(color, str) and color.startswith("0x"): color = "#" + color[2:]
                result[biome] = color
            return result
        return {}

    def get_full_biome_data(self):
        if self._tracker and isinstance(getattr(self._tracker, "biome_data", None), dict):
            return self._tracker.biome_data
        return {}

    def open_appdata(self):
        try:
            if hasattr(os, "startfile"):
                os.startfile(str(APPDATA_BASE))
            else:
                if sys.platform == "darwin":
                    subprocess.Popen(["open", str(APPDATA_BASE)])
                elif sys.platform.startswith("linux"):
                    subprocess.Popen(["xdg-open", str(APPDATA_BASE)])
                else:
                    webbrowser.open(f"file://{APPDATA_BASE}")
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def save_config(self, config_data):
        prev_anti_afk = False
        if self._tracker and isinstance(getattr(self._tracker, "config", None), dict):
            prev_anti_afk = bool(self._tracker.config.get("anti_afk", False))

        cfg = dict(config_data) if isinstance(config_data, dict) else dict(self.get_config())

        # normalize auto pop biomes with whatever biome list we have
        biome_names = []
        if self._tracker and isinstance(getattr(self._tracker, "biome_data", None), dict):
            biome_names = list(self._tracker.biome_data.keys())
        cfg["auto_pop_biomes"] = normalize_auto_pop_biomes(cfg, biome_names=biome_names)


        if _cfg_bool(cfg, "fishing_failsafe_rejoin") and not _cfg_bool(cfg, "auto_reconnect"):
            cfg["fishing_failsafe_rejoin"] = False

        save_config(cfg)
        if self._tracker:
            if not isinstance(getattr(self._tracker, "config", None), dict):
                self._tracker.config = {}
            self._tracker.config.update(cfg)

            # sync webhook urls to the tracker
            if 'webhook_url' in cfg:
                self._tracker.webhook_urls = cfg['webhook_url']
                try:
                    if hasattr(self._tracker, "refresh_active_webhook_channels"):
                        self._tracker.refresh_active_webhook_channels(force=True)
                except Exception:
                    pass

            if self._tracker.detection_running:
                # hot-swap fishing mode
                if self._is_fishing_mode_enabled():
                    self._start_fishing_worker()
                else:
                    self._stop_fishing_worker()

                if not prev_anti_afk and self._tracker.config.get("anti_afk", False):
                    try:
                        threading.Thread(target=self._tracker.perform_anti_afk_action, daemon=True).start()
                    except Exception:
                        pass

    def export_calibration_data_to_downloads(self, calibration_data=None):
        try:
            export_data = dict(calibration_data) if isinstance(calibration_data, dict) else {}
            if not export_data:
                export_data = self.get_config() or {}

            downloads_dir = Path(os.path.expanduser("~/Downloads"))
            downloads_dir.mkdir(parents=True, exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = downloads_dir / f"macro_calibrations_{timestamp}.json"
            with open(output_path, "w", encoding="utf-8") as handle:
                json.dump({
                    "presets": [
                        {
                            "resolution": "",
                            "mode": "",
                            "calibrations": export_data,
                        }
                    ]
                }, handle, indent=4)

            return {"success": True, "path": str(output_path)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def import_config(self):
        try:
            if not self._window:
                return {"success": False, "error": "Window not available"}

            result = self._window.create_file_dialog(
                webview.FileDialog.OPEN, allow_multiple=False,
                file_types=("JSON Files (*.json)",),
            )
            if not result:
                return {"success": False, "error": "No file selected"}

            path = result[0] if isinstance(result, (list, tuple)) else result
            with open(path, "r", encoding="utf-8") as f:
                imported = json.loads(f.read())
            if not isinstance(imported, dict):
                return {"success": False, "error": "Invalid config file: must be a JSON object"}

            save_config(imported)

            if self._tracker:
                if not isinstance(getattr(self._tracker, "config", None), dict):
                    self._tracker.config = {}
                self._tracker.config.update(imported)
                if 'webhook_url' in imported:
                    self._tracker.webhook_urls = imported['webhook_url']
                try:
                    if hasattr(self._tracker, "refresh_active_webhook_channels"):
                        self._tracker.refresh_active_webhook_channels(force=True)
                except Exception: pass

            return {"success": True, "config": imported}
        except json.JSONDecodeError:
            return {"success": False, "error": "Invalid JSON file"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def export_theme(self, theme_data, filename="coteab_theme.json"):
        try:
            if not self._window:
                return {"success": False, "error": "Window not available"}

            result = self._window.create_file_dialog(
                webview.SAVE_DIALOG,
                save_filename=filename,
                file_types=("JSON Files (*.json)",)
            )

            if not result:
                return {"success": False, "error": "Cancelled"}

            path = result[0] if isinstance(result, (list, tuple)) else result

            with open(path, "w", encoding="utf-8") as f:
                json.dump(theme_data, f, indent=4)

            return {"success": True, "path": path}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def close_window(self):
        self._stop_fishing_worker()
        if self._window:
            try:
                self._window.destroy()
            except Exception:
                pass
        
        def delayed_exit():
            time.sleep(1.5)
            os._exit(0)
        threading.Thread(target=delayed_exit, daemon=True).start()
        return {"success": True}

    def minimize_window(self):
        if self._window:
            self._window.minimize()

    def toggle_maximize_window(self):
        if self._window:
            self._window.toggle_fullscreen()

    def set_always_on_top(self, enabled: bool):
        if self._window:
            try:
                try:
                    self._window.on_top = bool(enabled)
                except Exception:
                    try:
                        self._window.evaluate_js('window.focus && window.focus();')
                    except Exception:
                        pass
            except Exception as e:
                print(f"Failed to set always on top: {e}")
                try:
                    self._window.on_top = bool(enabled)
                except Exception:
                    pass

    def open_url(self, url: str):
        webbrowser.open(url)

    def get_macro_status(self):
        if self._tracker and getattr(self._tracker, 'detection_running', False):
            return "RUNNING"
        return "STOPPED"

    def get_macro_version(self):
        return current_version

    def _setup_emergency_server(self):
        class SafeModeHandler(BaseHTTPRequestHandler):
            api = self

            def do_GET(self):
                if self.path == "/health":
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"OK")
                else:
                    # Serve files from any valid dist directory
                    file_path = self.path.split('?')[0].lstrip('/')
                    if not file_path or file_path == 'index.html':
                        file_path = 'index.html'
                    
                    found_full_path = None
                    for dist_dir in _get_frontend_dist_dirs():
                        full_path = os.path.join(dist_dir, file_path)
                        if os.path.exists(full_path) and os.path.isfile(full_path):
                            found_full_path = full_path
                            break
                    
                    if found_full_path:
                        self.send_response(200)
                        if file_path.endswith('.js'): self.send_header('Content-type', 'application/javascript')
                        elif file_path.endswith('.css'): self.send_header('Content-type', 'text/css')
                        elif file_path.endswith('.html'): self.send_header('Content-type', 'text/html')
                        self.end_headers()
                        with open(found_full_path, 'rb') as f:
                            self.wfile.write(f.read())
                    else:
                        self.send_response(404)
                        self.end_headers()

            def do_POST(self):
                if self.path.startswith("/api/"):
                    method_name = self.path.replace("/api/", "")
                    content_length = int(self.headers.get('Content-Length', 0))
                    post_data = self.rfile.read(content_length)
                    try:
                        args = json.loads(post_data) if post_data else []
                    except json.JSONDecodeError:
                        self.send_response(400)
                        self.send_header('Content-Type', 'text/plain')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                        self.wfile.write(b'Invalid JSON data')
                        return

                    method = getattr(self.api, method_name, None)
                    if not callable(method):
                        self.send_response(404)
                        self.send_header('Content-Type', 'text/plain')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                        self.wfile.write(b'Method not found')
                        return

                    try:
                        if isinstance(args, list):
                            result = method(*args)
                        elif isinstance(args, dict):
                            result = method(**args)
                        else:
                            result = method()

                        self.send_response(200)
                        self.send_header('Content-Type', 'application/json')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                        self.wfile.write(json.dumps(result).encode())
                    except Exception as e:
                        self.send_response(500)
                        self.send_header('Content-Type', 'text/plain')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                        self.wfile.write(str(e).encode())
                else:
                    self.send_response(404)
                    self.send_header('Content-Type', 'text/plain')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    self.wfile.write(b'Not Found')

            def do_OPTIONS(self):
                self.send_response(200)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
                self.send_header('Access-Control-Allow-Headers', 'Content-Type')
                self.end_headers()

            def log_message(self, format, *args): pass

        self.emergency_port = random.randint(18000, 19000)
        def _run():
            try:
                server = ThreadingHTTPServer(('127.0.0.1', self.emergency_port), SafeModeHandler)
                print(f"Emergency Server running on http://127.0.0.1:{self.emergency_port}")
                server.serve_forever()
            except Exception as e:
                print(f"Server failed: {e}")

        threading.Thread(target=_run, daemon=True).start()

    def _setup_emergency_hotkey(self):
        def trigger():
            print("Emergency UI Triggered! Hiding main window...")
            if hasattr(self, '_window') and self._window:
                try:
                    self._window.hide()
                    print("Main window hidden.")
                except Exception as e:
                    print(f"Note: Could not hide window: {e}")

            url = f"http://127.0.0.1:{self.emergency_port}/index.html?safe_mode=1"
            webbrowser.open(url)
            print(f"Emergency UI opened in browser: {url}")

        try:
            # prefer pynput global hotkey on macOS
            from pynput import keyboard as _pynput_keyboard
            try:
                gh = _pynput_keyboard.GlobalHotKeys({"<ctrl>+<shift>+f10": trigger})
                gh.start()
            except Exception:
                # fallback to keyboard lib if available
                if hasattr(keyboard, 'add_hotkey'):
                    try:
                        keyboard.add_hotkey('ctrl+shift+f10', trigger)
                    except Exception:
                        pass
        except Exception:
            try:
                if hasattr(keyboard, 'add_hotkey'):
                    keyboard.add_hotkey('ctrl+shift+f10', trigger)
            except Exception:
                pass

    def get_active_modules(self):
        if not self._tracker: return {}
        t = self._tracker
        cfg = t.config
        
        modules = {
            "Biome Detection": { "active": t.detection_running, "enabled": True },
            "Aura Detection": { "active": t.detection_running and bool(cfg.get("enable_aura_detection", False)), "enabled": bool(cfg.get("enable_aura_detection", False)) },
            "Fishing Mode": { "active": t.detection_running and self._is_fishing_mode_enabled(), "enabled": bool(cfg.get("fishing_mode", False)) },
            "Auto Pop Buff": { "active": bool(getattr(t, "auto_pop_state", False)), "enabled": True },
            "Anti-AFK": { "active": t.detection_running and bool(cfg.get("anti_afk", True)), "enabled": bool(cfg.get("anti_afk", True)) },
            "Auto Merchant": { "active": bool(getattr(t, "on_auto_merchant_state", False)), "enabled": bool(cfg.get("merchant_teleporter", False)) },
            "BR / SC Sequence": { "active": bool(getattr(t, "_br_sc_running", False)), "enabled": bool(cfg.get("biome_randomizer", False)) or bool(cfg.get("strange_controller", False)) },
            "Eden Path": { "active": bool(getattr(t, "_eden_running", False)), "enabled": bool(cfg.get("go_to_eden_spawn", False)) },
            "Auto Eden Contract": { "active": bool(getattr(t, "_eden_running", False)), "enabled": bool(cfg.get("auto_eden_contract", False)) },
            "Egg Pathing": { "active": bool(getattr(t, "_egg_collecting", False)), "enabled": bool(cfg.get("collect_easter_egg", False)) },
            "Basic Obby": { "active": bool(getattr(t, "_obby_running", False)), "enabled": bool(cfg.get("enable_auto_obby", False)) },
            "Daily Quests": { "active": t.detection_running and bool(cfg.get("auto_claim_daily_quests", False)), "enabled": bool(cfg.get("auto_claim_daily_quests", False)) },
            "Potion Crafting": { "active": bool(getattr(t, "_potion_thread_active", False)), "enabled": bool(cfg.get("enable_potion_crafting", False)) },
            "Macro Idle Mode": { "active": bool(cfg.get("enable_idle_mode", False)), "enabled": bool(cfg.get("enable_idle_mode", False)) },
        }
        
        incompatibilities = []
        if cfg.get("enable_idle_mode", False):
            incompatibilities.append("Idle Mode is ON: Most automated actions are paused infinitely.")
        
        if cfg.get("go_to_eden_spawn", False) and bool(cfg.get("fishing_mode", False)):
            incompatibilities.append("Conflict: Both Eden Path and Fishing Mode are enabled. Fishing will take priority unless blocked.")

        if bool(cfg.get("enable_potion_crafting", False)) and bool(cfg.get("fishing_mode", False)):
            incompatibilities.append("Potion Crafting is enabled: It has the highest priority take over from Fishing Mode and cancels any automated actions.")

        return {
            "modules": modules,
            "incompatibilities": incompatibilities
        }

    def _is_fishing_mode_enabled(self):
        cfg = getattr(self._tracker, "config", None) if self._tracker else None
        if not isinstance(cfg, dict): return False
        if cfg.get("enable_idle_mode", False): return False
        return bool(cfg.get("fishing_mode", False))

    def _fishing_can_run(self):
        t = self._tracker
        if not t or not getattr(t, "detection_running", False): return False
        if not self._is_fishing_mode_enabled(): return False

        # pause during reconnect, but mark that we need to sell when we come back
        if getattr(t, "reconnecting_state", False):
            self._fishing_runtime_state["rejoin_in_progress"] = True
            return False
        if self._fishing_runtime_state.get("rejoin_in_progress"):
            self._fishing_runtime_state["rejoin_in_progress"] = False
            self._fishing_runtime_state["force_sell_on_next_cycle"] = True

        _STALE_TIMEOUT = 240
        now = time.time()
        blocking_flags = ("_egg_collecting", "_egg_collection_pending", "auto_pop_state")
        any_blocking = False

        for flag_name in blocking_flags:
            if getattr(t, flag_name, False):
                ts_key = f"_fishing_block_ts_{flag_name}"
                first_seen = self._fishing_runtime_state.get(ts_key, 0)
                if first_seen == 0:
                    self._fishing_runtime_state[ts_key] = now
                    any_blocking = True
                elif (now - first_seen) >= _STALE_TIMEOUT:
                    setattr(t, flag_name, False)
                    self._fishing_runtime_state[ts_key] = 0
                    try:
                        t.append_log(
                            f"[FishingMode] Force cleared stale '{flag_name}' flag "
                            f"after {_STALE_TIMEOUT}s — was blocking fishing."
                        )
                    except Exception: pass
                else:
                    any_blocking = True
            else:
                ts_key = f"_fishing_block_ts_{flag_name}"
                if self._fishing_runtime_state.get(ts_key, 0): self._fishing_runtime_state[ts_key] = 0

        if any_blocking: return False
        return True

    def _fishing_config_provider(self):
        t = self._tracker
        if t and isinstance(getattr(t, "config", None), dict):
            return dict(t.config)
        return load_config()

    def _on_fishing_failsafe_timeout(self):
        if not self._tracker: return
        biome = str(getattr(self._tracker, "current_biome", "") or "").upper().strip()

        # dont kill (yes kill) roblox during a rare biome lol, wait for it to end
        from biome_tracker.base_support import rare_biomes
        if biome in rare_biomes:
            self._tracker._pending_fishing_failsafe_rejoin = True
            try:
                self._tracker.append_log(f"[FishingMode] Failsafe timed out during {biome}; delaying rejoin.")
                self._tracker.send_webhook_status(
                    f"Fishing failsafe timed out during {biome}. Rejoin delayed until biome ends.",
                    color=0xffcc00,
                )
            except Exception: pass
            return

        try: self._tracker.terminate_roblox_processes()
        except Exception as e: print(f"Fishing failsafe close Roblox failed: {e}")

        if not self._fishing_config_provider().get("auto_reconnect", False):
            self._emit_fishing_failsafe_warning(
                "Fishing failsafe timeout: Roblox closed after 60s with no minigame. "
                "Enable PS reconnect in Misc so it can recover automatically."
            )

    def _run_fishing_br_sc_sequence(self):
        if not self._tracker: return False
        t = self._tracker
        old_override = getattr(t, "_fishing_br_sc_override", False)
        t._fishing_br_sc_override = True
        ran = False
        try:
            try: t.activate_roblox_window()
            except Exception: pass

            try:
                t._use_br_sc_impl("strange controller")
                t.last_sc_time = datetime.now()
                ran = True
            except Exception as e:
                print(f"Fishing SC step failed: {e}")
            try:
                t._use_br_sc_impl("biome randomizer")
                t.last_br_time = datetime.now()
                ran = True
            except Exception as e:
                print(f"Fishing BR step failed: {e}")
        except Exception as e:
            print(f"Fishing BR/SC sequence failed: {e}")
        finally:
            t._fishing_br_sc_override = old_override
        return ran

    def _run_fishing_merchant_sequence(self):
        if not self._tracker: return False
        t = self._tracker
        self._fishing_runtime_state["merchant_requires_reset"] = False
        old_override = getattr(t, "_fishing_br_sc_override", False)
        t._fishing_br_sc_override = True
        ran = False
        try:
            try: t.activate_roblox_window()
            except Exception: pass

            merchant_fn = getattr(t, "_merchant_teleporter_impl", None)
            if not callable(merchant_fn):
                print("Fishing merchant sequence skipped: _merchant_teleporter_impl unavailable")
                return False

            # reuse the same merchant logic so we get buy, webhook, limbo, everything
            merchant_fn()
            ran = bool(getattr(t, "_last_merchant_sequence_ran", False))
            self._fishing_runtime_state["merchant_requires_reset"] = bool(
                getattr(t, "_last_merchant_sequence_requires_reset", False)
            )
            if ran: t.last_mt_time = datetime.now()
        except Exception as e:
            print(f"Fishing merchant sequence failed: {e}")
        finally:
            t._fishing_br_sc_override = old_override
        return ran

    def _start_fishing_worker(self) -> None:
        if not self._tracker:
            return
        with self._fishing_lock:
            if self._fishing_thread and self._fishing_thread.is_alive():
                return
            self._fishing_stop_event.clear()

            def _run_fishing():
                try:
                    from biome_tracker.fishing import run_fishing_loop
                    run_fishing_loop(
                        stop_event=self._fishing_stop_event,
                        can_run_cb=self._fishing_can_run,
                        config_provider=self._fishing_config_provider,
                        log_prefix="[FishingMode]",
                        print_start_stop=True,
                        on_failsafe_timeout=self._on_fishing_failsafe_timeout,
                        run_br_sc_sequence_cb=self._run_fishing_br_sc_sequence,
                        run_merchant_sequence_cb=self._run_fishing_merchant_sequence,
                        activate_roblox_cb=self._tracker.activate_roblox_window,
                        close_chat_fn=self._tracker.close_chat_if_open,
                        runtime_state=self._fishing_runtime_state,
                        set_fishing_busy_cb=lambda busy: setattr(self._tracker, "_fishing_busy", busy),
                        on_f2_pressed_cb=lambda: (self.set_biome_detection(False), self._emit_shortcut("STOP")),
                        egg_ocr_check_cb=self._tracker._perform_egg_ocr_check,
                        merchant_ocr_check_cb=getattr(self._tracker, "_scheduled_merchant_ocr_check", None),
                    )
                except Exception as e:
                    print(f"Fishing worker failed: {e}")

            self._fishing_thread = threading.Thread(target=_run_fishing, daemon=True)
            self._fishing_thread.start()

    def _stop_fishing_worker(self) -> None:
        with self._fishing_lock:
            self._fishing_stop_event.set()
            t = self._fishing_thread
            if t and t.is_alive():
                t.join(timeout=1.0)
            if not t or not t.is_alive():
                self._fishing_thread = None

    def set_biome_detection(self, enabled):
        if not self._tracker:
            print("[set_biome_detection] Tracker not ready yet; ignoring call.")
            self._safe_eval_js('if(window.onMacroStatus) window.onMacroStatus("STOPPED");')
            return
        if enabled:
            if not self._tracker.detection_running:
                threading.Thread(target=self._tracker.start_detection, daemon=True).start()
            if self._is_fishing_mode_enabled():
                self._start_fishing_worker()
            else:
                self._stop_fishing_worker()
                try: self._tracker.start_potion_crafting()
                except Exception: pass
        else:
            self._stop_fishing_worker()
            self._tracker.stop_detection()
        self._emit_macro_status()


    def _safe_eval_js(self, js_code):
        if not self._window: return
        try:
            self._window.evaluate_js(js_code)
        except Exception: pass

    def _emit_macro_status(self):
        self._safe_eval_js(f'if(window.onMacroStatus) window.onMacroStatus("{self.get_macro_status()}");')

    def _emit_config_update(self):
        self._safe_eval_js('if(window.onConfigUpdated) window.onConfigUpdated();')

    def _emit_biome_update(self, biome):
        self._safe_eval_js(f'if(window.onBiomeUpdate) window.onBiomeUpdate("{biome}");')

    def _emit_shortcut(self, key):
        self._safe_eval_js(f'if(window.onShortcutEvent) window.onShortcutEvent("{key}");')

    def _emit_update_available(self, version, url):
        self._safe_eval_js(f'if(window.onUpdateAvailable) window.onUpdateAvailable("{version}", "{url}");')

    def _emit_update_status(self, status):
        self._safe_eval_js(f'if(window.onUpdateStatus) window.onUpdateStatus("{status}");')

    def _emit_fishing_failsafe_warning(self, msg):
        self._safe_eval_js(f"if(window.onFishingFailsafeWarning) window.onFishingFailsafeWarning({json.dumps(str(msg))});")

    def _request_biome_confirm(self, biome: str):
        self._biome_confirm_evt.clear()
        self._biome_confirm_result = None
        popup_window = None
        try:
            print(f"[BiomeConfirm] Spawning independent popup for biome: {biome}")
            fe = get_frontend_entry()
            popup_w, popup_h = 480, 400
            try:
                try:
                    screen = pyautogui.size()
                    screen_w, screen_h = int(screen.width), int(screen.height)
                except Exception:
                    screen_w, screen_h = 800, 600
                popup_x = (screen_w - popup_w) // 2
                popup_y = (screen_h - popup_h) // 2
            except Exception:
                popup_x, popup_y = 300, 200

            win_kwargs = {
                "title": f"\u26a0\ufe0f Rare Biome Detected \u2014 {biome} \u26a0\ufe0f",
                "js_api": self,
                "width": popup_w,
                "height": popup_h,
                "x": popup_x,
                "y": popup_y,
                "resizable": False,
            }

            base = fe["url"] if fe and "url" in fe else "http://localhost:5173"
            sep = "&" if "?" in base else "?"
            win_kwargs["url"] = f"{base}{sep}window=biome_confirm&biome={biome}"

            popup_window = webview.create_window(**win_kwargs)

            try:
                def _flash():
                    time.sleep(1.0)
                    try:
                        if popup_window:
                            try:
                                popup_window.evaluate_js('window.focus && window.focus();')
                            except Exception:
                                pass
                    except Exception:
                        pass
                threading.Thread(target=_flash, daemon=True).start()
            except Exception:
                pass

        except Exception as e:
            print(f"[BiomeConfirm] Failed to create popup window: {e}")
            return None

        responded = self._biome_confirm_evt.wait(timeout=10)

        try:
            if popup_window:
                popup_window.destroy()
        except Exception:
            pass

        if not responded:
            return None
        return self._biome_confirm_result

    def confirm_biome_response(self, confirmed: bool):
        self._biome_confirm_result = bool(confirmed)
        self._biome_confirm_evt.set()

    def apply_update(self, download_url: str, version: str = ""):
        if self._tracker:
            def _do_update():
                try:
                    self._emit_update_status("downloading")
                    self._tracker.download_and_apply_update(download_url, version=version)
                except Exception as e:
                    self._emit_update_status("failed")
            threading.Thread(target=_do_update, daemon=True).start()
            return True
        return False

    def check_for_updates(self):
        if not self._tracker:
            return False

        def _do_check():
            try:
                self._tracker.check_for_updates()
            except Exception as e:
                print(f"Update check failed: {e}")

        threading.Thread(target=_do_check, daemon=True).start()
        return True

    def get_update_available(self):
        if not self._tracker:
            return None
        try:
            latest_release = self._tracker._fetch_latest_release()
            if not isinstance(latest_release, dict):
                return None

            latest_version = str(latest_release.get("tag_name", "")).strip()
            if not latest_version:
                return None
            if self._tracker._is_same_version(latest_version, current_version):
                return None

            _asset_name, download_url = self._tracker._pick_update_exe_asset(latest_release)
            if not download_url:
                return None

            return {"version": latest_version, "url": download_url}
        except Exception as e:
            print(f"Direct update query failed: {e}")
            return None

    def send_webhook_status(self, status: str, color: int):
        if self._tracker and hasattr(self._tracker, 'send_webhook_status'):
            self._tracker.send_webhook_status(status, color)

    def check_winocr_status(self):
        try:
            import rapidocr_onnxruntime
        except ImportError:
            return {"installed": False, "version": None, "binary": None}

        version = None
        try:
            from importlib.metadata import version as get_version
            version = get_version("rapidocr_onnxruntime")
        except Exception:
            version = getattr(rapidocr_onnxruntime, "__version__", None)

        return {"installed": True, "version": version, "binary": "rapidocr_onnxruntime"}
    
    def test_webhook(self, url): return True  # placeholder

    def get_recorder_status(self):
        return getattr(self._tracker, "_is_recording", False) if self._tracker else False

    def start_macro_recording(self):
        if self._tracker: self._tracker.start_recording_path()

    def stop_macro_recording(self):
        if self._tracker: return self._tracker.stop_recording_path("obby", save_dir="paths")
        return "No tracker"

    def stop_macro_recording_potion(self, name: str):
         if self._tracker:
             return self._tracker.stop_recording_path(name, save_dir="crafting_files_do_not_open")
         return "No tracker"

    def _get_frontend_url(self):
         res = get_frontend_entry()
         return res["url"] if res else "http://localhost:5173"

    def _open_recorder(self, mode: str = "obby"):
         fe = get_frontend_entry()
         query = "window=recorder"
         if mode == "potion":
             query += "&mode=potion"
         title = "Potion Recorder" if mode == "potion" else "Obby Recorder"

         win_kwargs = {
             "title": title,
             "js_api": self,
             "width": 380,
             "height": 320,
             "resizable": True,
             "on_top": True,
         }

         base = fe["url"] if fe and "url" in fe else "http://localhost:5173"
         sep = "&" if "?" in base else "?"
         win_kwargs["url"] = f"{base}{sep}{query}"

         webview.create_window(**win_kwargs)

    def open_recorder_window(self):
         self._open_recorder("obby")

    def open_recorder_window_potion(self):
         self._open_recorder("potion")

    def list_potion_files(self):
         try:
             rec_dir = "crafting_files_do_not_open"
             if os.path.isdir(rec_dir):
                 return sorted([f for f in os.listdir(rec_dir) if f.lower().endswith(".json")])
         except Exception:
             pass
         return []

    def check_obby_path_exists(self):
        try:
            obby_file = os.path.join(os.getcwd(), "paths", "obby.json")
            if not os.path.isfile(obby_file):
                return False
            with open(obby_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return bool(data)
        except Exception:
            return False

    def replay_recording(self):
         if self._tracker:
             return self._tracker.replay_path_recording("obby", save_dir="paths")
         return "No tracker"

    def replay_potion_recording(self, name: str):
         if self._tracker:
             return self._tracker.replay_path_recording(name, save_dir="crafting_files_do_not_open")
         return "No tracker"

    def test_aura_keybind(self):
         if self._tracker:
             def test_record():
                 try:
                    keybind = self._tracker.aura_record_keybind_var.get()
                    if not keybind: return
                    keys = [key.strip() for key in keybind.split('+')]
                    time.sleep(2)
                    pyautogui.hotkey(*keys)
                 except Exception as e:
                    print(f"Error testing aura keybind: {e}")
             threading.Thread(target=test_record, daemon=True).start()

    def test_biome_keybind(self):
         if self._tracker:
             def test_record():
                 try:
                    keybind = self._tracker.rarest_biome_keybind_var.get()
                    if not keybind: return
                    keys = [key.strip() for key in keybind.split('+')]
                    time.sleep(2)
                    pyautogui.hotkey(*keys)
                 except Exception as e:
                    print(f"Error testing biome keybind: {e}")
             threading.Thread(target=test_record, daemon=True).start()

    def align_camera(self):
         if self._tracker:
             self._tracker.align_camera()

    def emit_calibration_result(self, data):
         if self._window:
             js_data = json.dumps(data)
             self._window.evaluate_js(
                 f"if(window.onCalibrationResult) window.onCalibrationResult({js_data});"
                 f"if(window.onCalibrationResultMisc) window.onCalibrationResultMisc({js_data});"
             )

    def create_calibration_window(self, key="unknown", window_type="point"):
        self._calib_mgr.request_calibration(config_key=key, window_type=window_type)

    def display_calibration_on_screen(self, key: str, label: str = "", duration_ms: int = 2500):
        try:
            self._calib_mgr.request_display(
                config_key=key,
                label=label or key,
                duration_ms=duration_ms
            )
            return True
        except Exception:
            return False

    def display_all_fishing_calibrations_on_screen(self, duration_ms: int = 3000):
        try:
            cfg = self.get_config() if callable(getattr(self, "get_config", None)) else {}
            if not isinstance(cfg, dict):
                cfg = {}

            items = [
                {"key": "fishing_detect_pixel", "label": "Fishing Detect Pixel", "value": cfg.get("fishing_detect_pixel", [1176, 836])},
                {"key": "fishing_click_position", "label": "Start Fishing Button", "value": cfg.get("fishing_click_position", [862, 843])},
                {"key": "fishing_midbar_sample_pos", "label": "Mid Bar Sample Position", "value": cfg.get("fishing_midbar_sample_pos", [955, 767])},
                {"key": "fishing_close_button_pos", "label": "Fishing Close Button", "value": cfg.get("fishing_close_button_pos", [1113, 342])},
                {"key": "fishing_bar_region", "label": "Fishing Bar Region", "value": cfg.get("fishing_bar_region", [757, 762, 405, 21])},
                {"key": "fishing_flarg_dialogue_box", "label": "Captain Flarg Dialogue Box", "value": cfg.get("fishing_flarg_dialogue_box", [1046, 782])},
                {"key": "fishing_shop_open_button", "label": "Open Fishing Shop", "value": cfg.get("fishing_shop_open_button", [616, 938])},
                {"key": "fishing_shop_sell_tab", "label": "Fishing Shop Sell Tab", "value": cfg.get("fishing_shop_sell_tab", [1285, 312])},
                {"key": "fishing_shop_close_button", "label": "Close Fishing Shop", "value": cfg.get("fishing_shop_close_button", [1458, 269])},
                {"key": "fishing_shop_first_fish", "label": "First Fish In Shop", "value": cfg.get("fishing_shop_first_fish", [827, 404])},
                {"key": "fishing_shop_sell_all_button", "label": "Sell All Button", "value": cfg.get("fishing_shop_sell_all_button", [662, 799])},
                {"key": "fishing_confirm_sell_all_button", "label": "Confirm Sell All Button", "value": cfg.get("fishing_confirm_sell_all_button", [800, 619])},
            ]
            self._calib_mgr.request_display_many(items=items, duration_ms=duration_ms)
            return True
        except Exception:
            return False


def launch_app(api_class, tracker=None):
    
    tracker = tracker or BiomeTracker()
    api = api_class(tracker)
    tracker.on_stats_update = api._emit_config_update
    tracker.on_biome_update = api._emit_biome_update
    tracker.on_update_available = api._emit_update_available
    tracker.on_update_status = api._emit_update_status
    tracker.on_biome_confirm_request = api._request_biome_confirm
    tracker.on_status_change = lambda status: api._emit_macro_status()

    fe = get_frontend_entry()
    win_args = {
        "title": f"Macteab Macro {current_version}",
        "js_api": api,
        "width": 985, "height": 550,
        "min_size": (550, 500),
        "resizable": True, "frameless": False,
        "url": fe["url"] if fe and "url" in fe else "http://localhost:5173"
    }

    window = webview.create_window(**win_args)
    api.set_window(window)

    try:
        from pynput import keyboard as _pynput_keyboard
        try:
            gh = _pynput_keyboard.GlobalHotKeys({
                '<f1>': lambda: threading.Thread(target=lambda: (api.set_biome_detection(True), api._emit_shortcut('START')), daemon=True).start(),
                '<f2>': lambda: threading.Thread(target=lambda: (api.set_biome_detection(False), api._emit_shortcut('STOP')), daemon=True).start(),
            })
            gh.start()
        except Exception:
            if hasattr(keyboard, 'add_hotkey'):
                try:
                    keyboard.add_hotkey('f1', lambda: (api.set_biome_detection(True), api._emit_shortcut('START')))
                except Exception:
                    pass
                try:
                    keyboard.add_hotkey('f2', lambda: (api.set_biome_detection(False), api._emit_shortcut('STOP')))
                except Exception:
                    pass
    except Exception:
        try:
            if hasattr(keyboard, 'add_hotkey'):
                keyboard.add_hotkey('f1', lambda: (api.set_biome_detection(True), api._emit_shortcut('START')))
                keyboard.add_hotkey('f2', lambda: (api.set_biome_detection(False), api._emit_shortcut('STOP')))
        except Exception:
            pass

    class _WvLog(logging.Handler):
        def emit(self, record):
            try: tracker.append_log(f"[pywebview] {record.getMessage()}")
            except Exception: pass
    logging.getLogger("pywebview").addHandler(_WvLog())

    try:
        if sys.platform == 'darwin':
            webview.start(debug=False, private_mode=False)
        else:
            tracker.append_log("Starting pywebview (edgechromium)")
            webview.start(debug=False, gui="edgechromium", private_mode=False)
    except Exception as e:
        print(f"[Webview] edgechromium failed: {e}")
        tracker.append_log(f"edgechromium failed: {e}, retrying default...")
        try: webview.start(debug=False, private_mode=False)
        except Exception as e2:
            print(f"[Webview] Default backend also failed: {e2}")
            tracker.append_log(f"Default backend also failed: {e2}")

    return tracker

def stop_app(tracker):
    if tracker and getattr(tracker, "detection_running", False): tracker.stop_detection()

def main():

    ensure_workspace_files()
    tracker = None
    api = Api(tracker=None)
    api._setup_emergency_server()
    api._setup_emergency_hotkey()
    try:
        fe = get_frontend_entry()
        win_args = {
            "title": f"Macteab Macro {current_version}",
            "js_api": api,
            "width": 985, "height": 550,
            "min_size": (550, 500),
            "resizable": True, "frameless": False,
            "url": fe["url"] if fe and "url" in fe else "http://localhost:5173"
        }

        window = webview.create_window(**win_args)
        api._window = window

        def _background_init():
            nonlocal tracker
            try:
                from biome_tracker.core import BiomeTracker
                tracker = BiomeTracker()
                canonical = _read_cli_value("--coteab-target", "CoteabMacro")
                old_pid_raw = _read_cli_value("--coteab-old-pid", "")
                try: old_pid = int(old_pid_raw) if old_pid_raw else None
                except Exception: old_pid = None

                if tracker.maybe_self_rename_to_canonical_exe(canonical, old_pid=old_pid):
                    window.destroy()
                    return

                if _cfg_bool(getattr(tracker, "config", {}), "auto_update_enabled", True):
                    if tracker.apply_startup_auto_update():
                        window.destroy()
                        return


                api._tracker = tracker
                tracker.on_stats_update = api._emit_config_update
                tracker.on_biome_update = api._emit_biome_update
                tracker.on_update_available = api._emit_update_available
                tracker.on_update_status = api._emit_update_status
                tracker.on_biome_confirm_request = api._request_biome_confirm
                tracker.on_status_change = lambda status: api._emit_macro_status()
                tracker.on_remote_start = lambda: api.set_biome_detection(True)
                tracker.on_remote_stop = lambda: api.set_biome_detection(False)
                api.set_window(window)

            except Exception as exc:
                print(f"Background init error: {exc}")
                traceback.print_exc()
                try:
                    tracker._safe_eval_js(
                        f'if(window.onMacroStatus) window.onMacroStatus("STOPPED");'
                        f'console.error("Macro init failed: {str(exc).replace(chr(34), chr(39))}");'
                    )
                except Exception:
                    pass

        # ---- F1/F2 hotkeys ----
        try:
            from pynput import keyboard as _pynput_keyboard
            try:
                gh = _pynput_keyboard.GlobalHotKeys({
                    '<f1>': lambda: threading.Thread(target=lambda: (api.set_biome_detection(True), api._emit_shortcut('START')), daemon=True).start(),
                    '<f2>': lambda: threading.Thread(target=lambda: (api.set_biome_detection(False), api._emit_shortcut('STOP')), daemon=True).start(),
                })
                gh.start()
            except Exception:
                if hasattr(keyboard, 'add_hotkey'):
                    try:
                        keyboard.add_hotkey('f1', lambda: (api.set_biome_detection(True), api._emit_shortcut('START')))
                    except Exception:
                        pass
                    try:
                        keyboard.add_hotkey('f2', lambda: (api.set_biome_detection(False), api._emit_shortcut('STOP')))
                    except Exception:
                        pass
        except Exception:
            try:
                if hasattr(keyboard, 'add_hotkey'):
                    keyboard.add_hotkey('f1', lambda: (api.set_biome_detection(True), api._emit_shortcut('START')))
                    keyboard.add_hotkey('f2', lambda: (api.set_biome_detection(False), api._emit_shortcut('STOP')))
            except Exception:
                pass

        class _WvLog(logging.Handler):
            def emit(self, record):
                try:
                    if tracker: tracker.append_log(f"[pywebview] {record.getMessage()}")
                except Exception: pass
        logging.getLogger("pywebview").addHandler(_WvLog())

        try:
            if sys.platform == 'darwin':
                webview.start(func=_background_init, debug=False, private_mode=False)
            else:
                webview.start(func=_background_init, debug=False, gui="edgechromium", private_mode=False)
        except Exception as e:
            print(f"[Webview] edgechromium failed: {e}")
            try: webview.start(func=_background_init, debug=False, private_mode=False)
            except Exception as e2:
                print(f"[Webview] Default backend also failed: {e2}")

        return 0

    except KeyboardInterrupt:
        print("Exited (Ctrl+C)")
        return 130
    except Exception as exc:
        print(f"Fatal error: {exc}")
        traceback.print_exc()
        return 1
    finally:
        try:
            stop_app(tracker)
        except Exception:
            pass
        try:
            sync_config()
        except Exception:
            pass
        # If an emergency server object was stored on the API, try to shut it down.
        try:
            srv = getattr(api, "_emergency_server", None)
            if srv:
                try:
                    srv.shutdown()
                except Exception:
                    pass
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())