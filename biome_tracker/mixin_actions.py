import cv2
import numpy as np
import platform
import threading
import time
import datetime
import os
import json
import requests
import pyautogui
import psutil
import subprocess
import sys
import re
import random
import difflib
import hashlib
import queue
import shutil
from .base_support import *
from .ocr_support import ensure_rapidocr_env
from datetime import datetime, timedelta, timezone

try:
    from AppKit import NSWorkspace
    from Quartz import (
        CGWindowListCopyWindowInfo, kCGWindowListOptionOnScreenOnly,
        kCGNullWindowID, CGWindowListCreateImage, CGRectMake,
        kCGWindowImageDefault
    )
    from Quartz.CoreGraphics import CGEventCreateKeyboardEvent, CGEventPost, kCGHIDEventTap
except ImportError:
    print("Warning: pyobjc not installed. Run: pip install pyobjc")

IS_MACOS = True if platform.system() == "Darwin" else False
try:
    import pyperclip
except ImportError:
    pyperclip = None

def _safe_type_text_pyautogui(text: str, azerty_mode: bool = False) -> None:
    text = str(text)
    if azerty_mode and pyperclip is not None:
        try:
            pyperclip.copy(text)
            pyautogui.hotkey('command', 'v')
            return
        except Exception:
            pass
    pyautogui.write(text, interval=0.01)

class ActionsMixin:
    def initialize_paths_and_files(self):
        try:
            paths_folder = os.path.join(os.getcwd(), "paths")
            os.makedirs(paths_folder, exist_ok=True)

            try:
                from biome_tracker.config import get_base_path
                import shutil
                source_paths = os.path.join(str(get_base_path()), "paths")
            except Exception:
                source_paths = None

            base_url = "https://raw.githubusercontent.com/raandomdev/Noteab-Macro/refs/heads/main/paths/"
            for filename in ["obby.json", "eden.json", "egg_route1.json", "egg_route2.json", "egg_route3.json"]:
                file_path = os.path.join(paths_folder, filename)
                if not os.path.exists(file_path):
                    if source_paths and os.path.exists(os.path.join(source_paths, filename)):
                        try:
                            shutil.copy2(os.path.join(source_paths, filename), file_path)
                            self.append_log(f"Copied {filename} from local workspace")
                            continue
                        except Exception:
                            pass
                    try:
                        response = requests.get(base_url + filename, timeout=5)
                        response.raise_for_status()
                        open(file_path, "w", encoding="utf-8").write(response.text)
                        self.append_log(f"Downloaded {filename}")
                    except Exception as e:
                        self.error_logging(e, f"Failed to download {filename}")
                else:
                    self.append_log(f"{filename} already exists")
        except Exception as e:
            self.error_logging(e, "Error in initialize_paths_and_files")

    def _safe_type_text(self, text):
        _safe_type_text_pyautogui(text, self.config.get("azerty_mode", False))

    def _get_rapidocr_reader(self):
        reader = getattr(self, "_easyocr_reader", None)
        if reader is not None:
            return reader

        ocr_lock = getattr(self, "_easyocr_lock", None)
        if ocr_lock is None:
            ocr_lock = threading.Lock()
            self._easyocr_lock = ocr_lock

        with ocr_lock:
            reader = getattr(self, "_easyocr_reader", None)
            if reader is not None:
                return reader

            try:
                if not ensure_rapidocr_env():
                    raise ImportError("rapidocr_onnxruntime is not installed")

                from rapidocr_onnxruntime import RapidOCR

                self._easyocr_reader = RapidOCR()
                self.easyocr_active = True
                self.append_log("[OCR] RapidOCR initialized")
            except ImportError as import_err:
                self.append_log(f"[OCR] RapidOCR not installed: {import_err}")
                self._easyocr_reader = None
            except Exception as init_err:
                self._easyocr_reader = None
                self.append_log(f"[OCR] RapidOCR initialization failed: {init_err}")

            return self._easyocr_reader

    def warmup_ocr_for_macos(self):
        if platform.system() != 'Darwin':
            return

        try:
            self.append_log("[OCR] Warming up RapidOCR for macOS...")
            reader = self._get_rapidocr_reader()
            if reader is None:
                raise ImportError('RapidOCR is unavailable')

            dummy_img = np.zeros((32, 128, 3), dtype=np.uint8)
            reader.ocr(dummy_img)
            self.append_log("[OCR] Warmup complete - RapidOCR ready")
        except ImportError as e:
            self.append_log(f"[OCR] RapidOCR unavailable: {e}")
        except Exception as e:
            self.append_log(f"[OCR] Warmup failed: {e}")

    def extract_text_with_easyocr(self, region, timeout_seconds: float = 2.0, retry_delay: float = 0.20):
        try:
            x, y, width, height = region

            ocr_lock = getattr(self, "_easyocr_lock", None)
            if ocr_lock is None:
                ocr_lock = threading.Lock()
                self._easyocr_lock = ocr_lock

            with ocr_lock:
                reader = self._get_rapidocr_reader()
                if reader is None:
                    return ""

                end_time = time.monotonic() + max(0.0, float(timeout_seconds))
                last_text = ""

                while time.monotonic() < end_time:
                    screenshot = pyautogui.screenshot(region=(x, y, width, height))
                    image_rgb = np.array(screenshot.convert('RGB'))

                    raw_result, _ = reader.ocr(image_rgb)
                    extracted_parts = []
                    if isinstance(raw_result, (list, tuple)):
                        for item in raw_result:
                            if isinstance(item, (list, tuple)) and len(item) >= 2:
                                candidate = item[1]
                                if isinstance(candidate, str) and candidate.strip():
                                    extracted_parts.append(candidate.strip())
                                elif isinstance(candidate, (list, tuple)) and candidate and isinstance(candidate[0], str):
                                    extracted_parts.append(candidate[0].strip())
                            elif isinstance(item, str) and item.strip():
                                extracted_parts.append(item.strip())

                    text = " ".join(part for part in extracted_parts if part).strip()
                    text = "".join(c if ord(c) < 128 else "" for c in text).strip()

                    if text:
                        self.append_log(f"[RapidOCR] Extracted text: '{text}'")
                        return text

                    last_text = text
                    if time.monotonic() + float(retry_delay) >= end_time:
                        break
                    time.sleep(float(retry_delay))

                if last_text:
                    final_text = "".join(c if ord(c) < 128 else "" for c in last_text).strip()
                    if final_text:
                        self.append_log(f"[RapidOCR] Extracted text: '{final_text}'")
                        return final_text

                self.append_log("[RapidOCR] No text detected after waiting.")
                return ""

        except Exception as e:
            try:
                self.error_logging(e, "Error extracting text with RapidOCR")
            except (UnicodeEncodeError, UnicodeDecodeError):
                self.error_logging(e, "Error extracting text with RapidOCR (unicode)")
            return ""

    def load_notice_tab(self):
        url = "https://raw.githubusercontent.com/raandomdev/Noteab-Macro/refs/heads/main/assets/noticetabcontents.txt"
        data = ""
        try:
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            data = r.text
        except Exception as e:
            print(f"Error loading noticetabcontents.txt from {url}: {e}")
            self.error_logging(e, f"Error loading noticetabcontents.txt from {url}")

        return data

    def is_roblox_focused(self):
        try:
            workspace = NSWorkspace.sharedWorkspace()
            active_app = workspace.activeApplication()
            if active_app:
                app_name = active_app.get('NSApplicationName', '').lower()
                return 'roblox' in app_name
        except Exception:
            pass
        return False

    def _is_fishing_blocked(self) -> bool:
        try:
            return (
                bool(self.is_fishing_mode_enabled())
                and not bool(getattr(self, "_remote_running", False))
                and not bool(getattr(self, "_fishing_br_sc_override", False))
                and not bool(self.config.get("enable_idle_mode", False))
            ) or bool((getattr(self, "_egg_collecting", False) or getattr(self, "_eden_running", False) or getattr(self, "_potion_thread_active", False)))
        except Exception:
            return False

    def _sleep_with_cancel(self, seconds: float, poll: float = 0.05) -> bool:
        end = time.monotonic() + max(0.0, float(seconds))
        while time.monotonic() < end:
            if (not self.detection_running
                    or self._is_fishing_blocked()
                    or bool(getattr(self, "auto_pop_state", False))):
                return False
            remaining = end - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(poll, remaining))
        return (self.detection_running
                and not self._is_fishing_blocked()
                and not bool(getattr(self, "auto_pop_state", False)))

    def update_theme(self, theme_name):
        self.root.style.theme_use(theme_name)
        self.config["selected_theme"] = theme_name
        self.save_config()

    def _get_update_api_url(self):
        return os.environ.get(
            "COTEAB_UPDATE_API_URL",
            "https://api.github.com/repos/raandomdev/Noteab-Macro/releases/latest",
        )

    def _normalize_version(self, value):
        try:
            v = str(value or "").strip().lower()
            if v.startswith("v"):
                v = v[1:]
            return v
        except Exception:
            return ""

    def _is_same_version(self, a, b):
        return self._normalize_version(a) == self._normalize_version(b)

    def _fetch_latest_release(self):
        try:
            response = requests.get(self._get_update_api_url(), timeout=12)
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict):
                return payload
        except Exception as e:
            print(f"Failed to fetch latest release metadata: {e}")
        return None

    def _pick_update_exe_asset(self, release_payload):
        assets = release_payload.get("assets", []) if isinstance(release_payload, dict) else []
        if not isinstance(assets, list):
            return "", ""

        preferred = {
            "coteabmacro.app",
            "coteabmacro.dmg",
            "coteab-macro.app",
            "coteab_macro.dmg",
        }
        exe_candidates = []
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            name = str(asset.get("name", "")).strip()
            url = str(asset.get("browser_download_url", "")).strip()
            if not name or not url:
                continue
            lower_name = name.lower()
            if lower_name in preferred:
                return name, url
            if lower_name.endswith(".app") or lower_name.endswith(".dmg"):
                exe_candidates.append((name, url))

        if exe_candidates:
            return exe_candidates[0]
        return "", ""

    def _spawn_detached_exe(self, exe_path, extra_args=None):
        try:
            cmd = [os.path.abspath(exe_path)]
            if extra_args:
                cmd.extend([str(x) for x in extra_args])

            subprocess.Popen(
                cmd,
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except Exception as e:
            print(f"Failed to spawn detached process: {e}")
            return False

    def _download_and_stage_exe_update(self, download_url, asset_name="CoteabMacro"):
        if not getattr(sys, "frozen", False):
            return False

        current_dir = os.path.dirname(os.path.abspath(sys.executable))
        extension = ".app" if not asset_name.endswith(".dmg") else ".dmg"
        temp_exe = os.path.join(current_dir, f"CoteabMacro1{extension}")

        try:
            if os.path.exists(temp_exe):
                os.remove(temp_exe)
        except Exception:
            pass

        response = requests.get(download_url, timeout=120, stream=True)
        response.raise_for_status()

        with open(temp_exe, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 256):
                if chunk:
                    f.write(chunk)

        if not os.path.exists(temp_exe) or os.path.getsize(temp_exe) <= 0:
            raise RuntimeError("Downloaded update file is empty")

        args = [
            "--coteab-finalize-update",
            "--coteab-old-pid",
            str(os.getpid()),
        ]
        if not self._spawn_detached_exe(temp_exe, args):
            raise RuntimeError("Failed to launch downloaded update executable")
        return True

    def _is_pid_alive(self, pid):
        try:
            pid_i = int(pid)
            if pid_i <= 0:
                return False
            proc = psutil.Process(pid_i)
            return proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
        except Exception:
            return False

    def maybe_self_rename_to_canonical_exe(self, canonical_target="CoteabMacro", old_pid=None):
        return False

    def _download_exe_to_folder(self, download_url, target_dir, asset_name="CoteabMacro"):
        os.makedirs(target_dir, exist_ok=True)

        base_name = os.path.basename(str(asset_name or "").strip()) or "CoteabMacro.app"
        target_path = os.path.join(target_dir, base_name)
        if os.path.exists(target_path):
            stem, ext = os.path.splitext(base_name)
            target_path = os.path.join(target_dir, f"{stem}_downloaded{ext}")

        response = requests.get(download_url, timeout=120, stream=True)
        response.raise_for_status()

        with open(target_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 256):
                if chunk:
                    f.write(chunk)

        if not os.path.exists(target_path) or os.path.getsize(target_path) <= 0:
            raise RuntimeError("Downloaded update file is empty")

        os.chmod(target_path, 0o755)
        return target_path

    def apply_startup_auto_update(self):
        try:
            if not getattr(sys, "frozen", False):
                return False

            latest_release = self._fetch_latest_release()
            if not latest_release:
                return False

            latest_version = str(latest_release.get("tag_name", "")).strip()
            if not latest_version or self._is_same_version(latest_version, current_ver):
                return False

            asset_name, download_url = self._pick_update_exe_asset(latest_release)
            if not download_url:
                print("Update available, but no asset was found in latest release.")
                return False

            print("Downloading the new Coteab Macro update...")
            if self._download_and_stage_exe_update(download_url, asset_name=asset_name):
                print(f"Update {latest_version} downloaded. Restarting into the new executable...")
                return True
            return False
        except Exception as e:
            print(f"Startup auto-update failed: {e}")
            return False

    def check_for_updates(self):
        current_version = current_ver

        try:
            latest_release = self._fetch_latest_release()
            if not latest_release:
                return

            latest_version = str(latest_release.get("tag_name", "")).strip()
            if latest_version and not self._is_same_version(latest_version, current_version):
                asset_name, download_url = self._pick_update_exe_asset(latest_release)
                if not download_url:
                    return

                if hasattr(self, "on_update_available") and callable(self.on_update_available):
                    self.on_update_available(latest_version, download_url)

        except Exception as e:
            print(f"Failed to check for updates: {e}")

    def download_and_apply_update(self, download_url, version=""):
        try:
            if not download_url:
                if hasattr(self, "on_update_status") and callable(self.on_update_status):
                    self.on_update_status("failed")
                return False

            if hasattr(self, "on_update_status") and callable(self.on_update_status):
                self.on_update_status("downloading")

            guessed_name = os.path.basename(str(download_url).split("?", 1)[0]) or "CoteabMacro.app"
            if getattr(sys, "frozen", False):
                self._download_and_stage_exe_update(download_url, asset_name=guessed_name)

                if hasattr(self, "on_update_status") and callable(self.on_update_status):
                    self.on_update_status("done|restarting")

                time.sleep(0.25)
                os._exit(0)
            else:
                try:
                    base_dir = os.path.dirname(os.path.abspath(__file__))
                    project_root = os.path.dirname(base_dir)
                except Exception:
                    project_root = os.getcwd()

                downloaded_path = self._download_exe_to_folder(
                    download_url,
                    project_root,
                    asset_name=guessed_name,
                )

                if hasattr(self, "on_update_status") and callable(self.on_update_status):
                    self.on_update_status(f"done|{os.path.basename(downloaded_path)}")
                return True
        except Exception as e:
            print(f"Failed to download/apply update: {e}")
            if hasattr(self, "on_update_status") and callable(self.on_update_status):
                self.on_update_status("failed")
            return False

    def take_inventory_screenshot_now(self):
        try:
            if not getattr(self, "periodical_inventory_var", None) or not self.periodical_inventory_var.get():
                return
            if self.config.get("enable_idle_mode", False):
                return
            if not self.check_roblox_procs():
                return
            if (getattr(self, "_egg_collecting", False) or getattr(self, "_eden_running", False) or getattr(self, "_potion_thread_active", False)):
                return

            self.activate_roblox_window()
            search_bar = self.config.get("search_bar", [855, 358])
            inventory_menu = self.config.get("inventory_menu", [36, 535])
            items_tab = self.config.get("items_tab", [1272, 329])
            inventory_close_button = self.config.get("inventory_close_button", [1418, 298])
            if inventory_menu and inventory_menu[0]:
                pyautogui.click(inventory_menu[0], inventory_menu[1])
                time.sleep(0.35)
            if items_tab and items_tab[0]:
                pyautogui.click(items_tab[0], items_tab[1])
                time.sleep(1)
                pyautogui.click(search_bar[0], search_bar[1])
                time.sleep(0.35)
            try:
                screenshot_dir = os.path.join(os.getcwd(), "images")
                os.makedirs(screenshot_dir, exist_ok=True)
                filename = os.path.join(screenshot_dir, f"inventory_screenshot_{int(time.time())}.png")
                img = pyautogui.screenshot()
                img.save(filename)
                self.send_inventory_screenshot_webhook(filename)
                self.last_inventory_screenshot_time = datetime.now()
            except Exception as e:
                self.error_logging(e, "Error taking/sending forced inventory screenshot")
            try:
                if inventory_close_button and inventory_close_button[0]:
                    pyautogui.click(inventory_close_button[0], inventory_close_button[1])
                    time.sleep(0.22)
            except Exception as e:
                self.error_logging(e, "Error while closing inventory after forced screenshot")
        except Exception as e:
            self.error_logging(e, "Error in take_inventory_screenshot_now")

    def perform_glitched_enable_buff(self):
        try:
            if not self.config.get("enable_buff_glitched", False):
                return
            if self.config.get("enable_idle_mode", False):
                return
            if getattr(self, "enable_potion_crafting_var", None) and self.enable_potion_crafting_var.get(): return
            menu = self.config.get("glitched_menu_button", [0, 0])
            buff_enable = self.config.get("glitched_buff_enable_button", [0, 0])
            settings = self.config.get("glitched_settings_button", [0, 0])
            for _ in range(4):
                if not self.detection_running or self.reconnecting_state:
                    return
                self.activate_roblox_window()
                time.sleep(0.15)
            while True:
                if not self.detection_running or self.reconnecting_state:
                    return
                if not getattr(self, "_br_sc_running", False) and not getattr(self, "_mt_running", False) and not getattr(self, "auto_pop_state", False) and not getattr(self, "on_auto_merchant_state", False) and not (getattr(self, "_egg_collecting", False) or getattr(self, "_eden_running", False) or getattr(self, "_potion_thread_active", False)) and not self.config.get("enable_potion_crafting", False):
                    break
                time.sleep(0.67)
            if menu and menu[0]:
                pyautogui.click(menu[0], menu[1])
                time.sleep(0.67)
            if settings and settings[0]:
                pyautogui.click(settings[0], settings[1])
                time.sleep(0.67)
            if buff_enable and buff_enable[0]:
                pyautogui.click(buff_enable[0], buff_enable[1])
                time.sleep(0.67)
        except Exception as e:
            self.error_logging(e, "Error in perform_glitched_enable_buff")

    def _reset_on_rare_impl(self):
        try:
            if self.config.get("enable_idle_mode", False):
                return
            if not self.detection_running or self.reconnecting_state:
                return
            if getattr(self, "enable_potion_crafting_var", None) and self.enable_potion_crafting_var.get(): return
            for _ in range(4):
                if not self.detection_running:
                    return
                self.activate_roblox_window()
                time.sleep(0.15)
            pyautogui.keyDown("esc")
            pyautogui.keyUp("esc")
            time.sleep(0.3)
            pyautogui.keyDown('r')
            pyautogui.keyUp('r')
            time.sleep(0.3)
            pyautogui.keyDown("enter")
            pyautogui.keyUp("enter")
        except Exception:
            pass

    def _make_player_embed(self, kind, name, pid, ts_iso, duration_text=None, join_biome=None, left_biome=None):
        color = 3066993 if kind == "join" else 15158332
        title = "Player Joined" if kind == "join" else "Player Left"
        if kind == "join" and join_biome:
            title = f"Player Joined during {join_biome} biome"
        elif kind == "leave" and left_biome:
            title = f"Player Left during {left_biome} biome"
        desc = f"**{name}**\n`{pid}`"
        fields = []
        if duration_text:
            fields.append({"name": "Stayed", "value": duration_text, "inline": True})
        if kind == "leave" and join_biome:
            fields.append({"name": "Joined During", "value": f"{join_biome} biome", "inline": True})
        embed = {
            "title": title,
            "description": desc,
            "color": color,
            "timestamp": ts_iso,
            "footer": {"text": "Coteab Macro for macOS• Player Logger"},
            "fields": fields
        }
        return embed

    def _send_embeds_to_all(self, embeds):
        urls = self.get_webhook_list()
        if not urls:
            return
        payload = {"embeds": embeds}
        for url in urls:
            try:
                requests.post(url, json=payload, timeout=5)
            except Exception:
                pass

    def perform_quest_claim_sequence_sync(self):
        try:
            self._action_scheduler.enqueue_action(self._perform_quest_claim_sequence_impl, name="quest_claim", priority=5)
        except Exception:
            try:
                self._perform_quest_claim_sequence_impl()
            except Exception:
                pass

    def _perform_quest_claim_sequence_impl(self):
        try:
            if self.config.get("enable_idle_mode", False):
                return
            if self._is_fishing_blocked():
                return
            if not getattr(self, "auto_claim_quests_var", None) or not self.auto_claim_quests_var.get():
                return
            if (getattr(self, "_egg_collecting", False) or getattr(self, "_eden_running", False) or getattr(self, "_potion_thread_active", False)):
                return
            if getattr(self, "enable_potion_crafting_var", None) and self.enable_potion_crafting_var.get(): return
            if not self.check_roblox_procs():
                return
            self.activate_roblox_window()
            quest_menu = self.config.get("quest_menu", [0, 0])
            quest1 = self.config.get("quest1_button", [0, 0])
            quest2 = self.config.get("quest2_button", [0, 0])
            quest3 = self.config.get("quest3_button", [0, 0])
            claim_btn = self.config.get("claim_quest_button", [0, 0])

            for _ in range(4):
                if not self.detection_running or self._is_fishing_blocked():
                    return
                self.activate_roblox_window()
                if not self._sleep_with_cancel(0.15):
                    return

            if quest_menu and quest_menu[0]:
                pyautogui.click(quest_menu[0], quest_menu[1])
                if not self._sleep_with_cancel(0.5):
                    return

            try:
                screenshot_dir = os.path.join(os.getcwd(), "images")
                os.makedirs(screenshot_dir, exist_ok=True)
                filename = os.path.join(screenshot_dir, f"quest_screenshot_{int(time.time())}.png")
                img = pyautogui.screenshot()
                img.save(filename)
                self.send_quest_screenshot_webhook(filename)
            except Exception as e:
                self.error_logging(e, "Error taking/sending quest screenshot")

            if not self._sleep_with_cancel(0.5):
                return

            if quest1 and quest1[0]:
                pyautogui.click(quest1[0], quest1[1])
                if not self._sleep_with_cancel(0.5):
                    return
            if claim_btn and claim_btn[0]:
                pyautogui.click(claim_btn[0], claim_btn[1])
                if not self._sleep_with_cancel(0.5):
                    return

            if quest2 and quest2[0]:
                pyautogui.click(quest2[0], quest2[1])
                if not self._sleep_with_cancel(0.5):
                    return
            if claim_btn and claim_btn[0]:
                pyautogui.click(claim_btn[0], claim_btn[1])
                if not self._sleep_with_cancel(0.5):
                    return

            if quest3 and quest3[0]:
                pyautogui.click(quest3[0], quest3[1])
                if not self._sleep_with_cancel(0.5):
                    return
            if claim_btn and claim_btn[0]:
                pyautogui.click(claim_btn[0], claim_btn[1])
                if not self._sleep_with_cancel(0.5):
                    return
            inventory_close_button = self.config.get("inventory_close_button", [1418, 298])
            try:
                if inventory_close_button and inventory_close_button[0]:
                    pyautogui.click(inventory_close_button[0], inventory_close_button[1])
                    self._sleep_with_cancel(0.3)
            except Exception:
                pass

        except Exception as e:
            self.error_logging(e, "Error in perform_quest_claim_sequence_sync")

    def obby_path_loop(self):
        try:
            if self.config.get("enable_idle_mode", False):
                return
            if getattr(self, "enable_potion_crafting_var", None) and self.enable_potion_crafting_var.get(): return
        except Exception as e:
            self.error_logging(e, "Error in obby_path_loop")

        while self.detection_running:
            try:
                if self.is_fishing_mode_enabled():
                    time.sleep(2)
                    continue
                if not getattr(self, "enable_obby_var", None) or not self.enable_obby_var.get():
                    time.sleep(2)
                    continue

                try:
                    interval_min = float(self.obby_claim_interval_var.get())
                except Exception:
                    interval_min = 15.0

                if (datetime.now() - self.last_obby_claim) < timedelta(minutes=interval_min):
                    time.sleep(2)
                    continue

                if ((getattr(self, "_egg_collecting", False) or getattr(self, "_eden_running", False) or getattr(self, "_potion_thread_active", False)) or
                    getattr(self, "_br_sc_running", False) or
                    getattr(self, "_mt_running", False) or
                    getattr(self, "auto_pop_state", False) or
                    getattr(self, "on_auto_merchant_state", False) or
                    getattr(self, "config", {}).get("enable_potion_crafting", False)):
                    time.sleep(2)
                    continue

                self._action_scheduler.enqueue_action(
                    self._perform_obby_path_sequence_impl,
                    name="obby_path",
                    priority=0
                )
                self.last_obby_claim = datetime.now()
            except Exception as e:
                self.error_logging(e, "Error in obby_path_loop")
            time.sleep(1)

    def _perform_obby_path_sequence_impl(self):
        try:
            if self._is_fishing_blocked():
                return
            if not getattr(self, "enable_obby_var", None) or not self.enable_obby_var.get():
                return
            if not self.check_roblox_procs():
                return

            self._obby_running = True
            print("[Obby] Activating Roblox...")
            for _ in range(4):
                if not self.detection_running or self._is_fishing_blocked() or self.auto_pop_state:
                    self._obby_running = False
                    return
                self.activate_roblox_window()
                if not self._sleep_with_cancel(0.15):
                    self._obby_running = False
                    return

            print("[Obby] Resetting Character...")
            pyautogui.keyDown('esc')
            pyautogui.keyUp('esc')
            if not self._sleep_with_cancel(0.3):
                return
            pyautogui.keyDown('r')
            pyautogui.keyUp('r')
            if not self._sleep_with_cancel(0.3):
                return
            pyautogui.keyDown('enter')
            pyautogui.keyUp('enter')
            if not self._sleep_with_cancel(6):
                return

            if not self.detection_running or self._is_fishing_blocked() or self.auto_pop_state:
                return

            self.close_chat_if_open()
            if not self._sleep_with_cancel(0.2): return
            collections_button = self.config.get("collections_button", [0, 0])
            if collections_button and collections_button[0]:
                pyautogui.click(collections_button[0], collections_button[1])
                if not self._sleep_with_cancel(0.3):
                    return

            exit_collections_button = self.config.get("exit_collections_button", [0, 0])
            if exit_collections_button and exit_collections_button[0]:
                pyautogui.click(exit_collections_button[0], exit_collections_button[1])
                if not self._sleep_with_cancel(0.3):
                    return

            if not self.detection_running or self._is_fishing_blocked() or self.auto_pop_state:
                return
            
            start_x = exit_collections_button[0] if exit_collections_button and exit_collections_button[0] else 500
            start_y = exit_collections_button[1] if exit_collections_button and exit_collections_button[1] else 500

            pyautogui.moveTo(start_x, start_y)
            pyautogui.mouseDown(button="right")
            time.sleep(0.1)
            pyautogui.moveTo(start_x, start_y + 75, duration=0.2)
            time.sleep(0.05)
            pyautogui.mouseUp(button="right")
            pyautogui.keyDown('i')
            if not self._sleep_with_cancel(4.0):
                pyautogui.keyUp('i')
                return
            pyautogui.keyUp('i')
            if not self._sleep_with_cancel(0.3):
                return

            pyautogui.keyDown('o')
            if not self._sleep_with_cancel(0.85):
                pyautogui.keyUp('o')
                return
            pyautogui.keyUp('o')
            if not self._sleep_with_cancel(0.3):
                return

            use_float_aura = self.config.get("use_float_aura", False)
            if use_float_aura:
                aura_name = self.config.get("float_aura_name", "").strip()
                if aura_name:
                    current_aura = getattr(self, "last_aura_found", None)
                    if current_aura and current_aura == aura_name:
                        print(f"[Obby] Float Aura '{aura_name}' already equipped. Skipping.")
                    else:
                        print(f"[Obby] Equipping Float Aura: {aura_name}")
                        inventory_click_delay = int(self.config.get("inventory_click_delay", "0")) / 1000.0
                        aura_menu = self.config.get("aura_menu", [0, 0])
                        search_bar = self.config.get(
                            "aura_search_bar",
                            self.config.get("search_bar", [834, 364]),
                        )
                        close_btn = self.config.get("inventory_close_button", [0, 0])

                        if aura_menu and aura_menu[0] > 0:
                            pyautogui.click(aura_menu[0], aura_menu[1])
                            if not self._sleep_with_cancel(0.7 + inventory_click_delay):
                                return

                            if search_bar and search_bar[0] > 0:
                                pyautogui.click(search_bar[0], search_bar[1])
                                if not self._sleep_with_cancel(0.5 + inventory_click_delay):
                                    return
                                try:
                                    self._safe_type_text(aura_name)
                                except Exception:
                                    try:
                                        self._safe_type_text(aura_name.lower())
                                    except Exception:
                                        pass
                                if not self._sleep_with_cancel(0.8 + inventory_click_delay):
                                    return

                                first_aura_slot = self.config.get("first_aura_slot_pos", [0, 0])
                                if first_aura_slot and first_aura_slot[0] > 0:
                                    pyautogui.click(first_aura_slot[0], first_aura_slot[1])
                                    if not self._sleep_with_cancel(0.5 + inventory_click_delay):
                                        return

                                    equip_btn = self.config.get("equip_aura_button", [0, 0])
                                    if equip_btn and equip_btn[0] > 0:
                                        pyautogui.click(equip_btn[0], equip_btn[1])
                                        if not self._sleep_with_cancel(0.3 + inventory_click_delay):
                                            return

                            if close_btn and close_btn[0] > 0:
                                pyautogui.click(close_btn[0], close_btn[1])
                                if not self._sleep_with_cancel(0.5 + inventory_click_delay):
                                    return

            if not self.detection_running or self._is_fishing_blocked() or self.auto_pop_state:
                return

            obby_file = os.path.join(os.getcwd(), "paths", "obby.json")
            if os.path.exists(obby_file):
                print("[Obby] Starting obby macro playback...")
                self._run_obby_macro(obby_file)
            else:
                print("[Obby] Macro file not found: " + obby_file)

        except Exception as e:
            self.error_logging(e, "Error in _perform_obby_path_sequence_impl")
        finally:
            self._obby_running = False

    def _run_obby_macro(self, json_file_path):
        try:
            with open(json_file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            self.error_logging(e, f"Failed to load obby macro from {json_file_path}")
            return

        if isinstance(data, dict) and "events" in data:
            all_events = data["events"]
        elif isinstance(data, list):
            all_events = data
        else:
            print("[Obby] obby.json has unexpected format. Skipping.")
            return

        _ALLOWED_KEYS = {"w", "a", "s", "d", "space"}

        # Support the "start_offset"/"duration" format by converting each entry
        # into a key_down/key_up event pair, matching the internal format below.
        if all_events and isinstance(all_events[0], dict) and "start_offset" in all_events[0]:
            converted = []
            for e in all_events:
                key = str(e.get("key", "")).lower().strip()
                if key not in _ALLOWED_KEYS:
                    continue
                try:
                    start = float(e.get("start_offset", 0.0))
                    dur = float(e.get("duration", 0.0))
                except Exception:
                    continue
                if dur < 0:
                    dur = 0.0
                converted.append({"type": "key_down", "key": key, "t": start})
                converted.append({"type": "key_up", "key": key, "t": start + dur})
            all_events = converted

        events = [
            e for e in all_events
            if e.get("type") in ("key_down", "key_up") and e.get("key", "").lower() in _ALLOWED_KEYS
        ]
        if not events:
            print("[Obby] No movement events found in obby.json.")
            return

        events.sort(key=lambda ev: ev.get("t", 0.0))

        def _get_key_name(k):
            norm = k.strip().lower()
            if norm == "space":
                return "space"
            return norm

        def _key_down(k):
            key_name = _get_key_name(k)
            if key_name:
                pyautogui.keyDown(key_name)

        def _key_up(k):
            key_name = _get_key_name(k)
            if key_name:
                pyautogui.keyUp(key_name)

        non_vip = bool(self.config.get("non_vip_movement_path", False))
        speed_multiplier = 1.22 if non_vip else 1.0

        def _cancelled():
            return (
                not self.detection_running
                or not getattr(self, "enable_obby_var", None)
                or not self.enable_obby_var.get()
                or self._is_fishing_blocked()
                or self.reconnecting_state
                or self.auto_pop_state
            )

        pressed_keys = set()
        base_t = float(events[0].get("t", 0.0))
        time_scale = 1.0
        max_raw_t = 0.0
        for ev in events:
            try:
                raw_t = float(ev.get("t", 0.0))
            except Exception:
                raw_t = 0.0
            if raw_t > max_raw_t:
                max_raw_t = raw_t
        if max_raw_t > 1000.0:
            time_scale = 0.001

        start_wall = time.perf_counter()

        print(f"[Obby] Playback ({len(events)} events, speed_mult={speed_multiplier:.2f})...")
        try:
            for ev in events:
                if _cancelled():
                    print("[Obby] Cancelled during playback.")
                    return

                ev_t = (float(ev.get("t", base_t)) - base_t) * time_scale
                if speed_multiplier != 1.0 and ev_t > 0:
                    ev_t = ev_t / speed_multiplier
                target_wall = start_wall + ev_t

                while True:
                    now = time.perf_counter()
                    if now >= target_wall:
                        break
                    remaining = target_wall - now
                    if _cancelled():
                        print("[Obby] Cancelled during wait.")
                        return
                    if remaining > 0.002:
                        time.sleep(min(remaining * 0.5, 0.005))

                typ = str(ev.get("type", ""))
                k = str(ev.get("key", "")).lower().strip()
                try:
                    if typ == "key_down" and k:
                        _key_down(k)
                        pressed_keys.add(k)
                    elif typ == "key_up" and k:
                        _key_up(k)
                        pressed_keys.discard(k)
                except Exception:
                    pass

            print("[Obby] Macro finished successfully yatta")
        finally:
            for key_name in list(pressed_keys):
                try:
                    _key_up(key_name)
                except Exception:
                    pass
            for k in ("w", "a", "s", "d", "space"):
                try:
                    _key_up(k)
                except Exception:
                    pass
                time.sleep(0.02)

    def _run_eden_macro(self, json_file_path):
        try:
            with open(json_file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            self.error_logging(e, f"Failed to load eden macro from {json_file_path}")
            return

        if isinstance(data, dict) and "events" in data:
            all_events = data["events"]
        elif isinstance(data, list):
            all_events = data
        else:
            print("[Eden] eden.json has unexpected format. Skipping.")
            return

        _ALLOWED_KEYS = {"w", "a", "s", "d", "space"}
        events = [
            e for e in all_events
            if e.get("type") in ("key_down", "key_up") and str(e.get("key", "")).lower() in _ALLOWED_KEYS
        ]
        if not events:
            print("[Eden] No movement events found in eden.json.")
            return

        events.sort(key=lambda ev: float(ev.get("t", 0.0)))
        base_t = float(events[0].get("t", 0.0))
        time_scale = 1.0
        max_raw_t = 0.0
        for ev in events:
            try:
                raw_t = float(ev.get("t", 0.0))
            except Exception:
                raw_t = 0.0
            if raw_t > max_raw_t:
                max_raw_t = raw_t
        if max_raw_t > 1000.0:
            time_scale = 0.001

        def _cancelled():
            return not self.detection_running

        pressed_keys = set()
        start_wall = time.time()

        print(f"[Eden] Playback ({len(events)} events)...")
        try:
            for ev in events:
                if _cancelled():
                    print("[Eden] Cancelled during playback.")
                    return

                ev_t = (float(ev.get("t", base_t)) - base_t) * time_scale
                target_wall = start_wall + ev_t

                now = time.time()
                if target_wall > now:
                    if target_wall - now > 0.02:
                        time.sleep((target_wall - now) - 0.015)
                    while time.time() < target_wall:
                        if _cancelled():
                            print("[Eden] Cancelled during wait.")
                            return

                typ = str(ev.get("type", ""))
                k = str(ev.get("key", "")).lower().strip()

                if k:
                    try:
                        if typ == "key_down":
                            pyautogui.keyDown(k)
                            pressed_keys.add(k)
                        elif typ == "key_up":
                            pyautogui.keyUp(k)
                            pressed_keys.discard(k)
                    except Exception:
                        pass

            print("[Eden] Macro finished successfully!")
        finally:
            if pressed_keys:
                print(f"[Eden] Releasing {len(pressed_keys)} stuck keys...")
                for k in list(pressed_keys):
                    try:
                        pyautogui.keyUp(k)
                    except Exception:
                        pass

    # ── Easter Egg Collection ─────────────────────────────────────────
    def egg_collect_loop(self):
        while self.detection_running:
            try:
                if self.config.get("enable_idle_mode", False):
                    time.sleep(2)
                    continue
                if not self.config.get("collect_easter_egg", False):
                    time.sleep(2)
                    continue
                try:
                    interval_min = float(self.config.get("egg_collect_interval_min", "25"))
                except Exception:
                    interval_min = 25.0

                if (datetime.now() - getattr(self, "last_egg_collect_time", datetime.min)) < timedelta(minutes=interval_min):
                    time.sleep(2)
                    continue

                self._egg_collection_pending = True

                if (getattr(self, "_br_sc_running", False) or
                    getattr(self, "_mt_running", False) or
                    getattr(self, "auto_pop_state", False) or
                    getattr(self, "on_auto_merchant_state", False) or
                    getattr(self, "_auto_merchant_running", False) or
                    getattr(self, "_fishing_busy", False) or
                    self.reconnecting_state or
                    getattr(self, "_obby_running", False)):
                    time.sleep(2)
                    continue

                current_biome = str(getattr(self, "current_biome", "") or "").upper().strip()
                if current_biome in ("GLITCHED", "DREAMSPACE", "CYBERSPACE"):
                    time.sleep(2)
                    continue

                if (getattr(self, "enable_potion_crafting_var", None)
                    and self.enable_potion_crafting_var.get()):
                    time.sleep(2)
                    continue

                self._egg_collection_pending = True
                try:
                    self._action_scheduler.enqueue_action(self._scheduled_egg_collect, name="egg_collect", priority=4)
                    while getattr(self, "_egg_collection_pending", False) and self.detection_running:
                        time.sleep(1)
                except Exception as e:
                    self._egg_collection_pending = False
                    self._egg_collecting = False
                    self.error_logging(e, "Error enqueueing egg collect")
            except Exception as e:
                self.error_logging(e, "Error in egg_collect_loop")
            time.sleep(1)

    def _scheduled_egg_collect(self):
        try:
            self._egg_collecting = True
            time.sleep(3.5)
            if self.is_fishing_mode_enabled():
                close_btn = self.config.get("fishing_close_button_pos", [1113, 342])
                if close_btn and close_btn[0]:
                    self.activate_roblox_window()
                    time.sleep(0.3)
                    pyautogui.click(close_btn[0], close_btn[1])
                    time.sleep(1.0)
            self._perform_egg_collect_impl()
        except Exception as e:
            self.error_logging(e, "Error in _scheduled_egg_collect execution")
        finally:
            self._egg_collecting = False
            self._egg_collection_pending = False
            self.last_egg_collect_time = datetime.now()

    def _perform_egg_collect_impl(self):
        try:
            if not self.config.get("collect_easter_egg", False):
                return
            if not self.check_roblox_procs():
                return

            print("[EggCollect] Starting egg collection sequence...")
            self.append_log("[EggCollect] Starting egg collection sequence...")

            from .egg_collect import run_egg_collect_once, load_egg_config

            cfg = load_egg_config(self.config)

            def _should_continue():
                return (
                    self.detection_running
                    and not self.reconnecting_state
                    and not self.auto_pop_state
                )

            def _can_run():
                try:
                    return (
                        self.detection_running
                        and not self.reconnecting_state
                        and not self.auto_pop_state
                        and bool(self.config.get("collect_easter_egg", False))
                    )
                except Exception:
                    return False

            def _sleep_interruptible(seconds, poll=0.02):
                end = time.monotonic() + max(0.0, float(seconds))
                while time.monotonic() < end:
                    if not _should_continue() or not _can_run():
                        return False
                    remaining = end - time.monotonic()
                    if remaining <= 0:
                        break
                    time.sleep(min(poll, remaining))
                return _should_continue() and _can_run()

            run_egg_collect_once(
                cfg=cfg,
                sleep_interruptible=_sleep_interruptible,
                should_continue=_should_continue,
                can_run=_can_run,
                activate_roblox_cb=self.activate_roblox_window,
                close_chat_fn=lambda: self.close_chat_if_open(force=False),
                egg_ocr_check_cb=self._perform_egg_ocr_check,
            )
        except Exception as e:
            self.error_logging(e, "Error in _perform_egg_collect_impl")

    def _mouse_click(self, x, y, clicks=1):
        pyautogui.click(x, y, clicks=clicks, button='left')
        time.sleep(0.1)

    def send(self, text):
        pyautogui.write(text)

    def _mouse_move(self, x, y):
        pyautogui.moveTo(x, y)

    def _mouse_down(self, button="left"):
        pyautogui.mouseDown(button)

    def _mouse_up(self, button="left"):
        pyautogui.mouseUp(button)

    def _press_key(self, key, down=False):
        if down:
            pyautogui.keyDown(key)
        else:
            pyautogui.press(key)
            
    def press_and_release_key(self, key):
        pyautogui.keyDown(key)
        time.sleep(0.05)
        pyautogui.keyUp(key)
    def _release_key(self, key):
        pyautogui.keyUp(key)

    # ── Easter Egg OCR Special Detection ──────────────────────────────
    EGG_SPAWN_MESSAGES: list[tuple[str, str, str]] = [
        ("Dreamer Egg (Sky Festival)",           "wait. am i still dreaming?", "1 in 2,000,000,000"),
        ("Egg v2.0 (Y.O.L.K.E.G.G)",            "preparing protocol. do you want to be my friend?", "1 in 1,780,908,090"),
        ("The Egg of the Sky (Eggis)",           "scanning. egg cannon charging 2000%", "1 in 1,150,000,000"),
        ("Forest Egg (Eostre)",                  "let's have an egg hunt here!", "1 in 1,000,000,000"),
        ("Blooming Egg (Eggore)",                "don't forget to water the small plant", "1 in 700,000,000"),
        ("Angelic Egg (REVIVE)",                 "holy eggsus", "1 in 645,000,000"),
        ("Andromeda Egg (Eggsistance)",           "am i in spaaaace right now?", "1 in 307,777,777"),
        ("Either Royal Egg or Hatch Egg",        "a special egg has spawned", "1 in 80,000,000 / 1 in 40,000,000"),
    ]

    def eden_ocr_check_loop(self):
        last_check = time.monotonic()
        while self.detection_running:
            try:
                if not self.config.get("eden_detection", False):
                    time.sleep(2)
                    continue

                try:
                    interval_min = float(self.config.get("eden_check_interval", "5"))
                except Exception:
                    interval_min = 5.0

                interval_sec = max(60.0, interval_min * 60.0)

                if (time.monotonic() - last_check) < interval_sec:
                    time.sleep(2)
                    continue

                if getattr(self, "_eden_checking_pending", False) or getattr(self, "_eden_checking", False):
                    time.sleep(2)
                    continue

                try:
                    pending_high_priority = False
                    for item in list(self._action_scheduler._pq.queue):
                        qname = str(item[2]).lower()
                        if "br" in qname or "sc" in qname or "merchant" in qname or "portable" in qname:
                            pending_high_priority = True
                            break
                    if pending_high_priority:
                        time.sleep(2)
                        continue
                except Exception:
                    pass

                if (self.reconnecting_state or
                    self.auto_pop_state or
                    (getattr(self, "_egg_collecting", False) or getattr(self, "_eden_running", False) or getattr(self, "_potion_thread_active", False)) or
                    getattr(self, "_obby_running", False) or
                    getattr(self, "_br_sc_running", False) or
                    getattr(self, "_mt_running", False) or
                    getattr(self, "on_auto_merchant_state", False) or
                    getattr(self, "_auto_merchant_running", False) or
                    getattr(self, "_fishing_busy", False) or
                    self._is_fishing_blocked()):
                    time.sleep(2)
                    continue

                current_biome = str(getattr(self, "current_biome", "") or "").upper().strip()
                if current_biome in ("GLITCHED", "DREAMSPACE", "CYBERSPACE"):
                    time.sleep(2)
                    continue

                if (getattr(self, "enable_potion_crafting_var", None)
                    and self.enable_potion_crafting_var.get()):
                    time.sleep(2)
                    continue

                if not self.check_roblox_procs():
                    time.sleep(2)
                    continue

                self._eden_checking_pending = True
                last_check = time.monotonic()
                try:
                    self._action_scheduler.enqueue_action(self._scheduled_eden_ocr_check, name="eden_ocr", priority=4)
                    while getattr(self, "_eden_checking_pending", False) and self.detection_running:
                        time.sleep(1)
                except Exception as e:
                    self._eden_checking_pending = False
                    self._eden_checking = False
                    self.error_logging(e, "Error enqueueing eden ocr")

            except Exception as e:
                self.error_logging(e, "Error in eden_ocr_check_loop")
            time.sleep(1)

    def _scheduled_eden_ocr_check(self):
        try:
            self._eden_checking = True
            print("[Eden ocr] Starting eden ocr check")
            chat_box_region = self.config.get("chat_box_ocr_pos", [0, 0, 0, 0])
            if not chat_box_region or len(chat_box_region) < 4: return
            if chat_box_region[2] <= 0 or chat_box_region[3] <= 0: return

            chat_hover = self.config.get("chat_hover_pos", [272, 252])
            chat_ocr_region = self.config.get("chat_tab_ocr_pos", [341, 83, 210, 40])
            chat_close = self.config.get("chat_close_button", [174, 40])

            if not (chat_hover and chat_hover[0] and chat_close and chat_close[0]): return

            for _ in range(3):
                self.activate_roblox_window()
                time.sleep(0.15)

            sw = pyautogui.size()
            pyautogui.moveTo(sw.width // 2, sw.height // 2)
            time.sleep(0.6)
            pyautogui.moveTo(chat_hover[0], chat_hover[1])
            time.sleep(0.6)

            chat_is_open = False
            for attempt in range(1, 3):
                tab_text = self.extract_text_with_easyocr(tuple(chat_ocr_region)).lower()
                if fuzzy_match_any(tab_text, ["here", "general", "server message"], threshold=0.8):
                    chat_is_open = True
                    break
                if attempt < 2:
                    time.sleep(0.35)

            if not chat_is_open:
                pyautogui.click(chat_close[0], chat_close[1])
                time.sleep(0.8)

                pyautogui.moveTo(chat_hover[0], chat_hover[1])
                time.sleep(0.5)

                for attempt in range(1, 3):
                    tab_text = self.extract_text_with_easyocr(tuple(chat_ocr_region)).lower()
                    if fuzzy_match_any(tab_text, ["general", "server message"], threshold=0.8):
                        chat_is_open = True
                        break
                    if attempt < 2:
                        time.sleep(0.35)

            if not chat_is_open:
                self.append_log("[EdenOCR] Could not confirm chat is open. Skipping OCR check.")
                return

            text = self.extract_text_with_easyocr(tuple(chat_box_region)).lower()
            if not text: return

            _PLAYER_TAGS = [
                "[fan]", "[vip]", "[vip+]", "[donator]", "[contributor]",
                "[cm]", "[dev]", "[moderator]", "[admin]", "[owner]",
                "[og]", "[tester]", "[youtuber]", "[rolls]"
            ]
            _TAG_LOOKBACK = 100

            def _is_player_message(match_pos: int) -> bool:
                start = max(0, match_pos - _TAG_LOOKBACK)
                prefix = text[start:match_pos]
                return any(tag in prefix for tag in _PLAYER_TAGS)

            _EDEN_FUZZY_THRESHOLD = 0.8
            fuzzy_target = "devourer of the void, eden has appeared"

            found_eden = False

            exact_pos = text.find(fuzzy_target)
            if exact_pos != -1:
                if not _is_player_message(exact_pos):
                    found_eden = True
                else:
                    print("[eden ocr] meh u aint slick lil bro")
                    self.append_log("[Eden OCR] 'Eden' exact string detected but it's just some random player trolling shit")
            else:
                win_len = len(fuzzy_target)
                if win_len <= len(text):
                    for i in range(len(text) - win_len + 1):
                        window = text[i:i + win_len]
                        ratio = difflib.SequenceMatcher(None, fuzzy_target, window).ratio()
                        if ratio >= _EDEN_FUZZY_THRESHOLD:
                            if not _is_player_message(i):
                                found_eden = True
                            else:
                                print("[eden ocr] STOP TRYING THIS DOGSHIT")
                                self.append_log("[Eden OCR] 'Eden' fuzzy string detected but it's just some random player trolling shit")
                            break

            if not found_eden: return

            # Skip if eden recently found to prevent spam
            _EDEN_OCR_COOLDOWN_SEC = 2400 # 40 mins
            last_eden_time = getattr(self, "_last_eden_ocr_found_time", 0)
            now = time.monotonic()
            if (now - last_eden_time) < _EDEN_OCR_COOLDOWN_SEC: return
            self._last_eden_ocr_found_time = now

            print(f"[EdenOCR] Eden spawn detected!")
            self.append_log(f"[EdenOCR] Eden spawn detected!")

            should_ping = self.config.get("ping_eden", False)
            discord_user_id = str(self.config.get("eden_user_id", "")).strip() if should_ping else ""
            screenshot_path = None

            try:
                if self.is_roblox_focused():
                    x, y, w, h = int(chat_box_region[0]), int(chat_box_region[1]), int(chat_box_region[2]), int(chat_box_region[3])
                    img = pyautogui.screenshot(region=(x, y, w, h))
                    screenshot_dir = os.path.join(os.getcwd(), "images")
                    os.makedirs(screenshot_dir, exist_ok=True)
                    screenshot_path = os.path.join(screenshot_dir, f"eden_ocr_{int(time.time())}.png")
                    img.save(screenshot_path)
            except Exception as e:
                print(f"[EdenOCR] Failed to take chat screenshot: {e}")
                screenshot_path = None

            try:
                self.send_eden_ocr_webhook(discord_user_id, screenshot_path=screenshot_path)
            except Exception as e:
                print(f"[EdenOCR] Failed to send webhook: {e}")

        except Exception as e:
            self.error_logging(e, "Error in _scheduled_eden_ocr_check")
        finally:
            try:
                chat_close = self.config.get("chat_close_button", [174, 40])
                if chat_close and chat_close[0]:
                    pyautogui.click(chat_close[0], chat_close[1])
            except Exception:
                pass
            self._eden_checking = False
            self._eden_checking_pending = False

    def merchant_ocr_check_loop(self):
        last_check = time.monotonic()
        while self.detection_running:
            try:
                if not self.config.get("merchant_ocr", False):
                    time.sleep(2)
                    continue

                try:
                    interval_sec = float(self.config.get("merchant_ocr_interval", "60"))
                except Exception:
                    interval_sec = 60.0

                interval_sec = max(2.0, interval_sec)

                if (time.monotonic() - last_check) < interval_sec:
                    time.sleep(2)
                    continue

                if getattr(self, "_merchant_checking_pending", False) or getattr(self, "_merchant_checking", False):
                    time.sleep(2)
                    continue

                try:
                    pending_high_priority = False
                    for item in list(self._action_scheduler._pq.queue):
                        qname = str(item[2]).lower()
                        if "br" in qname or "sc" in qname or "merchant" in qname or "portable" in qname or "eden_ocr" in qname or "egg_ocr" in qname:
                            pending_high_priority = True
                            break
                    if pending_high_priority:
                        time.sleep(2)
                        continue
                except Exception:
                    pass

                if (self.reconnecting_state or
                    self.auto_pop_state or
                    (getattr(self, "_egg_collecting", False) or getattr(self, "_eden_running", False) or getattr(self, "_potion_thread_active", False)) or
                    getattr(self, "_obby_running", False) or
                    getattr(self, "_br_sc_running", False) or
                    getattr(self, "_mt_running", False) or
                    getattr(self, "on_auto_merchant_state", False) or
                    getattr(self, "_auto_merchant_running", False) or
                    getattr(self, "_fishing_busy", False) or
                    self._is_fishing_blocked()):
                    time.sleep(2)
                    continue

                current_biome = str(getattr(self, "current_biome", "") or "").upper().strip()
                if current_biome in ("GLITCHED", "CYBERSPACE", "DREAMSPACE"):
                    time.sleep(2)
                    continue

                if (getattr(self, "enable_potion_crafting_var", None)
                    and self.enable_potion_crafting_var.get()):
                    time.sleep(2)
                    continue

                if not self.check_roblox_procs():
                    time.sleep(2)
                    continue

                self._merchant_checking_pending = True
                last_check = time.monotonic()
                try:
                    self._action_scheduler.enqueue_action(self._scheduled_merchant_ocr_check, name="merchant_ocr", priority=4)
                    while getattr(self, "_merchant_checking_pending", False) and self.detection_running:
                        time.sleep(1)
                except Exception as e:
                    self._merchant_checking_pending = False
                    self._merchant_checking = False
                    self.error_logging(e, "Error enqueueing merchant ocr")

            except Exception as e:
                self.error_logging(e, "Error in merchant_ocr_check_loop")
            time.sleep(1)

    def _scheduled_merchant_ocr_check(self):
        try:
            self._merchant_checking = True
            print("[Merchant OCR] Starting merchant ocr check")
            chat_box_region = self.config.get("chat_box_ocr_pos", [0, 0, 0, 0])
            if not chat_box_region or len(chat_box_region) < 4: return
            if chat_box_region[2] <= 0 or chat_box_region[3] <= 0: return

            chat_hover = self.config.get("chat_hover_pos", [272, 252])
            chat_ocr_region = self.config.get("chat_tab_ocr_pos", [341, 83, 210, 40])
            chat_close = self.config.get("chat_close_button", [174, 40])

            if not (chat_hover and chat_hover[0] and chat_close and chat_close[0]): return

            for _ in range(3):
                self.activate_roblox_window()
                time.sleep(0.15)

            sw = pyautogui.size()
            pyautogui.moveTo(sw.width // 2, sw.height // 2)
            time.sleep(0.6)
            pyautogui.moveTo(chat_hover[0], chat_hover[1])
            time.sleep(0.6)

            chat_is_open = False
            for attempt in range(1, 3):
                tab_text = self.extract_text_with_easyocr(tuple(chat_ocr_region)).lower()
                if fuzzy_match_any(tab_text, ["general", "server message"], threshold=0.8):
                    chat_is_open = True
                    break
                if attempt < 2:
                    time.sleep(0.35)

            if not chat_is_open:
                pyautogui.click(chat_close[0], chat_close[1])
                time.sleep(0.8)

                pyautogui.moveTo(chat_hover[0], chat_hover[1])
                time.sleep(0.5)

                for attempt in range(1, 3):
                    tab_text = self.extract_text_with_easyocr(tuple(chat_ocr_region)).lower()
                    if fuzzy_match_any(tab_text, ["general", "server message"], threshold=0.8):
                        chat_is_open = True
                        break
                    if attempt < 2:
                        time.sleep(0.35)

            if not chat_is_open:
                self.append_log("[Merchant OCR] Could not confirm chat is open. Skipping OCR check.")
                return

            text = self.extract_text_with_easyocr(tuple(chat_box_region)).lower()
            if not text: return

            _PLAYER_TAGS = [
                "[fan]", "[vip]", "[vip+]", "[donator]", "[contributor]",
                "[cm]", "[dev]", "[moderator]", "[admin]", "[owner]",
                "[og]", "[tester]", "[youtuber]", "[rolls]"
            ]
            _TAG_LOOKBACK = 100

            def _is_player_message(match_pos: int) -> bool:
                start = max(0, match_pos - _TAG_LOOKBACK)
                prefix = text[start:match_pos]
                return any(tag in prefix for tag in _PLAYER_TAGS)

            _MARI_FUZZY = "[merchant]: mari has arrived on the island..."
            _JESTER_FUZZY = "[merchant]: jester has arrived on the island!!"
            _RIN_FUZZY = "[merchant]: rin has arrived on the island!!"
            _NON_MERCHANT_NAMES = {"lime"}
            found_merchant = ""

            for target in [_MARI_FUZZY, _JESTER_FUZZY, _RIN_FUZZY]:
                expected_name = target.split(":")[1].strip().split(" ")[0].lower()
                exact_pos = text.find(target)
                if exact_pos != -1:
                    if not _is_player_message(exact_pos):
                        found_merchant = expected_name
                        break
                else:
                    win_len = len(target)
                    if win_len <= len(text):
                        for i in range(len(text) - win_len + 1):
                            window = text[i:i + win_len]
                            ratio = difflib.SequenceMatcher(None, target, window).ratio()
                            if ratio >= 0.8:
                                if not _is_player_message(i):
                                    try:
                                        actual_name = window.split(":")[1].strip().split(" ")[0].lower()
                                    except (IndexError, AttributeError):
                                        actual_name = ""
                                    if actual_name in _NON_MERCHANT_NAMES: break
                                    name_ratio = difflib.SequenceMatcher(None, expected_name, actual_name).ratio()
                                    if name_ratio >= 0.6: found_merchant = expected_name
                                break

            if not found_merchant: return

            _MERCHANT_OCR_COOLDOWN_SEC = 1500 # 25 mins
            last_merchant_time = getattr(self, "_last_merchant_ocr_found_time", 0)
            now = time.monotonic()
            if (now - last_merchant_time) < _MERCHANT_OCR_COOLDOWN_SEC: return
            self._last_merchant_ocr_found_time = now

            print(f"[Merchant OCR] {found_merchant.title()} spawn detected!")
            self.append_log(f"[Merchant OCR] {found_merchant.title()} spawn detected!")
            screenshot_path = None
            try:
                if self.is_roblox_focused():
                    x, y, w, h = int(chat_box_region[0]), int(chat_box_region[1]), int(chat_box_region[2]), int(chat_box_region[3])
                    img = pyautogui.screenshot(region=(x, y, w, h))
                    screenshot_dir = os.path.join(os.getcwd(), "images")
                    os.makedirs(screenshot_dir, exist_ok=True)
                    screenshot_path = os.path.join(screenshot_dir, f"merchant_ocr_{int(time.time())}.png")
                    img.save(screenshot_path)
            except Exception as e:
                print(f"[Merchant OCR] Failed to take chat screenshot: {e}")
                screenshot_path = None

            try:
                if hasattr(self, "send_merchant_webhook"):
                    self.send_merchant_webhook(found_merchant.title(), screenshot_path=screenshot_path, source='ocr')
                    if hasattr(self, "last_merchant_sent"): self.last_merchant_sent[(found_merchant.title(), 'ocr')] = time.time()

            except Exception as e:
                print(f"[Merchant OCR] Failed to send webhook: {e}")

        except Exception as e:
            self.error_logging(e, "Error in _scheduled_merchant_ocr_check")
        finally:
            try:
                chat_close = self.config.get("chat_close_button", [174, 40])
                if chat_close and chat_close[0]:
                    pyautogui.click(chat_close[0], chat_close[1])
            except Exception:
                pass
            self._merchant_checking = False
            self._merchant_checking_pending = False

    def egg_ocr_check_loop(self):
        last_check = time.monotonic()
        while self.detection_running:
            try:
                if not self.config.get("egg_ocr_detect_special", False):
                    time.sleep(2)
                    continue

                if (time.monotonic() - last_check) < 25.0:
                    time.sleep(1)
                    continue

                try:
                    pending_high_priority = False
                    for item in list(self._action_scheduler._pq.queue):
                        qname = str(item[2]).lower()
                        if "br" in qname or "sc" in qname or "merchant" in qname or "portable" in qname:
                            pending_high_priority = True
                            break
                    if pending_high_priority:
                        time.sleep(2)
                        continue
                except Exception:
                    pass

                if (self.reconnecting_state or
                    self.auto_pop_state or
                    (getattr(self, "_egg_collecting", False) or getattr(self, "_eden_running", False) or getattr(self, "_potion_thread_active", False)) or
                    getattr(self, "_obby_running", False) or
                    getattr(self, "_br_sc_running", False) or
                    getattr(self, "_mt_running", False) or
                    getattr(self, "on_auto_merchant_state", False) or
                    getattr(self, "_auto_merchant_running", False) or
                    getattr(self, "_fishing_busy", False) or
                    self._is_fishing_blocked()):
                    time.sleep(2)
                    continue

                current_biome = str(getattr(self, "current_biome", "") or "").upper().strip()
                if current_biome in ("GLITCHED", "DREAMSPACE", "CYBERSPACE"):
                    time.sleep(2)
                    continue

                if (getattr(self, "enable_potion_crafting_var", None)
                    and self.enable_potion_crafting_var.get()):
                    time.sleep(2)
                    continue

                if not self.check_roblox_procs():
                    time.sleep(2)
                    continue

                last_check = time.monotonic()
                self._perform_egg_ocr_check()

            except Exception as e:
                self.error_logging(e, "Error in egg_ocr_check_loop")
            time.sleep(1)

    def _perform_egg_ocr_check(self):
        try:
            chat_box_region = self.config.get("chat_box_ocr_pos", [0, 0, 0, 0])
            if not chat_box_region or len(chat_box_region) < 4: return
            if chat_box_region[2] <= 0 or chat_box_region[3] <= 0: return

            chat_hover = self.config.get("chat_hover_pos", [272, 252])
            chat_ocr_region = self.config.get("chat_tab_ocr_pos", [341, 83, 210, 40])
            chat_close = self.config.get("chat_close_button", [174, 40])

            if not (chat_hover and chat_hover[0] and chat_close and chat_close[0]): return

            for _ in range(3):
                self.activate_roblox_window()
                time.sleep(0.15)

            sw = pyautogui.size()
            pyautogui.moveTo(sw.width // 2, sw.height // 2)
            time.sleep(0.6)
            pyautogui.moveTo(chat_hover[0], chat_hover[1])
            time.sleep(0.6)

            chat_is_open = False
            for attempt in range(1, 3):
                tab_text = self.extract_text_with_easyocr(tuple(chat_ocr_region)).lower()
                if fuzzy_match_any(tab_text, ["general", "server message"], threshold=0.8):
                    chat_is_open = True
                    break
                if attempt < 2:
                    time.sleep(0.35)

            if not chat_is_open:
                pyautogui.click(chat_close[0], chat_close[1])
                time.sleep(0.8)

                pyautogui.moveTo(chat_hover[0], chat_hover[1])
                time.sleep(0.5)

                for attempt in range(1, 3):
                    tab_text = self.extract_text_with_easyocr(tuple(chat_ocr_region)).lower()
                    if fuzzy_match_any(tab_text, ["general", "server message"], threshold=0.8):
                        chat_is_open = True
                        break
                    if attempt < 2:
                        time.sleep(0.35)

            if not chat_is_open:
                self.append_log("[EggOCR] Could not confirm chat is open. Skipping OCR check.")
                return

            text = self.extract_text_with_easyocr(tuple(chat_box_region)).lower()
            if not text: return
            _PLAYER_TAGS = [
                "[fan]", "[vip]", "[vip+]", "[donator]", "[contributor]",
                "[cm]", "[dev]", "[moderator]", "[admin]", "[owner]",
                "[og]", "[tester]", "[youtuber]", "[rolls]"
            ]
            _TAG_LOOKBACK = 100

            def _is_player_message(match_pos: int) -> bool:
                start = max(0, match_pos - _TAG_LOOKBACK)
                prefix = text[start:match_pos]
                return any(tag in prefix for tag in _PLAYER_TAGS)

            egg_spawned_pos = text.find("egg spawned")
            if egg_spawned_pos == -1: return

            all_trolled = True
            search_start = 0
            while True:
                pos = text.find("egg spawned", search_start)
                if pos == -1: break
                if not _is_player_message(pos):
                    all_trolled = False
                    break
                search_start = pos + 1
            if all_trolled:
                self.append_log("[EggOCR] 'egg spawned' detected but it's just some random player trolling shit...")
                return

            _EGG_FUZZY_THRESHOLD = 0.8
            found_egg_name = None
            found_message = None
            found_rarity = None
            found_match_pos = -1

            for egg_name, unique_substr, aura_rarity in self.EGG_SPAWN_MESSAGES:
                exact_pos = text.find(unique_substr)
                if exact_pos != -1:
                    if not _is_player_message(exact_pos):
                        found_egg_name = egg_name
                        found_message = unique_substr
                        found_rarity = aura_rarity
                        found_match_pos = exact_pos
                        break
                    continue

                win_len = len(unique_substr)
                if win_len > len(text): continue
                for i in range(len(text) - win_len + 1):
                    window = text[i:i + win_len]
                    ratio = difflib.SequenceMatcher(None, unique_substr, window).ratio()
                    if ratio >= _EGG_FUZZY_THRESHOLD:
                        if not _is_player_message(i):
                            found_egg_name = egg_name
                            found_message = unique_substr
                            found_rarity = aura_rarity
                            found_match_pos = i
                        break
                if found_egg_name: break

            if not found_egg_name:
                found_egg_name = "Unknown Egg"
                found_message = "egg spawned"
                found_rarity = "Unknown"

            _EGG_OCR_COOLDOWN_SEC = 600
            last_egg = getattr(self, "_last_egg_ocr_found", None)
            last_egg_time = getattr(self, "_last_egg_ocr_found_time", 0)
            now = time.monotonic()
            if last_egg == found_egg_name and (now - last_egg_time) < _EGG_OCR_COOLDOWN_SEC: return
            self._last_egg_ocr_found = found_egg_name
            self._last_egg_ocr_found_time = now

            print(f"[EggOCR] Egg spawn detected: {found_egg_name} | Aura rarity: {found_rarity}")
            self.append_log(f"[EggOCR] Egg spawn detected: {found_egg_name} | Aura rarity: {found_rarity}")

            discord_user_id = str(self.config.get("egg_ocr_discord_userid", "")).strip()
            screenshot_path = None

            try:
                if self.is_roblox_focused():
                    x, y, w, h = int(chat_box_region[0]), int(chat_box_region[1]), int(chat_box_region[2]), int(chat_box_region[3])
                    img = pyautogui.screenshot(region=(x, y, w, h))
                    screenshot_dir = os.path.join(os.getcwd(), "images")
                    os.makedirs(screenshot_dir, exist_ok=True)
                    screenshot_path = os.path.join(screenshot_dir, f"egg_ocr_{int(time.time())}.png")
                    img.save(screenshot_path)
            except Exception as e:
                print(f"[EggOCR] Failed to take chat screenshot: {e}")
                screenshot_path = None

            try:
                self.send_egg_ocr_webhook(found_egg_name, found_rarity, discord_user_id, screenshot_path=screenshot_path)
            except Exception as e:
                print(f"[EggOCR] Failed to send webhook: {e}")

        except Exception as e:
            self.error_logging(e, "Error in _perform_egg_ocr_check")
        finally:
            try:
                chat_close = self.config.get("chat_close_button", [174, 40])
                if chat_close and chat_close[0]:
                    pyautogui.click(chat_close[0], chat_close[1])
            except Exception:
                pass

    def perform_quest_reroll(self, quest_index):
        try:
            if not getattr(self, "auto_claim_quests_var", None):
                pass
            if not self.check_roblox_procs():
                return
            for _ in range(4):
                if not self.detection_running:
                    return
                self.activate_roblox_window()
                time.sleep(0.15)
            quest_menu = self.config.get("quest_menu", [0, 0])
            quest1 = self.config.get("quest1_button", [0, 0])
            quest2 = self.config.get("quest2_button", [0, 0])
            quest3 = self.config.get("quest3_button", [0, 0])
            reroll_btn = self.config.get("quest_reroll_button", [0, 0])
            if quest_menu and quest_menu[0]:
                pyautogui.click(quest_menu[0], quest_menu[1])
                time.sleep(0.5)
            try:
                qbtn = quest1
                if str(quest_index) == "2":
                    qbtn = quest2
                elif str(quest_index) == "3":
                    qbtn = quest3
                if qbtn and qbtn[0]:
                    pyautogui.click(qbtn[0], qbtn[1])
                    time.sleep(0.4)
                if reroll_btn and reroll_btn[0]:
                    pyautogui.click(reroll_btn[0], reroll_btn[1])
                    time.sleep(0.45)

                inventory_close_button = self.config.get("inventory_close_button", [1418, 298])
                try:
                    if inventory_close_button and inventory_close_button[0]:
                        pyautogui.click(inventory_close_button[0], inventory_close_button[1])
                        time.sleep(0.3)
                except Exception:
                    pass
            except Exception:
                pass
        except Exception as e:
            try:
                self.error_logging(e, "Error in perform_quest_reroll")
            except Exception:
                pass

    def quest_claim_loop(self):
        last_claim_time = datetime.min
        while self.detection_running:
            try:
                if self.is_fishing_mode_enabled():
                    time.sleep(2)
                    continue
                if not getattr(self, "auto_claim_quests_var", None) or not self.auto_claim_quests_var.get():
                    time.sleep(2)
                    continue
                try:
                    interval_min = float(self.auto_claim_interval_var.get())
                except Exception:
                    interval_min = 30.0
                if (datetime.now() - last_claim_time) < timedelta(minutes=interval_min):
                    time.sleep(2)
                    continue
                with self.lock:
                    if not self.detection_running:
                        break
                    self._action_scheduler.enqueue_action(self.perform_periodic_aura_screenshot_sync, name="periodical:aura", priority=2)
                    time.sleep(0.5)
                    self._action_scheduler.enqueue_action(self.perform_periodic_inventory_screenshot_sync, name="periodical:inventory", priority=3)
                    time.sleep(0.5)
                    self._action_scheduler.enqueue_action(self.perform_quest_claim_sequence_sync, name="periodic:quest_claim", priority=4)
                    last_claim_time = datetime.now()
            except Exception as e:
                self.error_logging(e, "Error in quest_claim_loop")
            time.sleep(1)

    def perform_eden_path_sync(self):
        if not self.detection_running:
            print("[Eden Pathing] Aborted: detection not running")
            return
        self._eden_running = True

        def _eden_sleep(seconds):
            end = time.monotonic() + max(0.0, float(seconds))
            while time.monotonic() < end:
                if not self.detection_running: return False
                remaining = end - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(0.05, remaining))
            return self.detection_running

        try:
            print("[Eden Pathing] Activating Roblox...")
            if not self.check_roblox_procs():
                print("[Eden Pathing] No Roblox process found, aborting")
                return
            for _ in range(4):
                if not self.detection_running:
                    print("[Eden Pathing] Aborted during activation: detection stopped")
                    return
                self.activate_roblox_window()
                time.sleep(0.15)

            # 2. Reset Character
            print("[Eden Pathing] Resetting Character...")
            pyautogui.press_and_release('esc')
            if not _eden_sleep(1.25): return
            pyautogui.press_and_release('r')
            if not _eden_sleep(1.25): return
            pyautogui.press_and_release('enter')
            if not _eden_sleep(5): return

            if not self.detection_running:
                return

            self.close_chat_if_open()

            if not _eden_sleep(0.2): return
            collections_button = self.config.get("collections_button", [0, 0])
            if collections_button and collections_button[0]:
                pyautogui.click(collections_button[0], collections_button[1])
                if not _eden_sleep(0.65): return

            exit_collections_button = self.config.get("exit_collections_button", [0, 0])
            if exit_collections_button and exit_collections_button[0]:
                pyautogui.click(exit_collections_button[0], exit_collections_button[1])
                if not _eden_sleep(0.65): return

            if not self.detection_running:
                return

            # 4. Camera Adjustment
            start_x = exit_collections_button[0] if exit_collections_button and exit_collections_button[0] else 500
            start_y = exit_collections_button[1] if exit_collections_button and exit_collections_button[1] else 500

            pyautogui.moveTo(start_x, start_y)
            pyautogui.mouseDown(button="right")
            time.sleep(0.1)
            pyautogui.moveTo(start_x, start_y + 75, duration=0.2)
            time.sleep(0.05)
            pyautogui.mouseUp(button="right")
            try:
                pyautogui.keyDown('i')
            except Exception:
                pass
            if not _eden_sleep(4.0):
                try: pyautogui.keyUp('i')
                except: pass
                return
            try:
                pyautogui.keyUp('i')
            except Exception:
                pass
            if not _eden_sleep(0.3): return

            try:
                pyautogui.keyDown('o')
            except Exception:
                pass
            if not _eden_sleep(1.05):
                try: pyautogui.keyUp('o')
                except: pass
                return
            try:
                pyautogui.keyUp('o')
            except Exception:
                pass
            if not _eden_sleep(0.3): return

            if not self.detection_running:
                return

            print("[Eden Pathing] Using portable crack...")
            self._teleport_crack_impl(ignore_eden=True)
            self.last_crack_time = datetime.now()
            if not _eden_sleep(10): return
            if not self.detection_running:
                return

            eden_file = os.path.join(os.getcwd(), "paths", "eden.json")
            if os.path.exists(eden_file):
                print("[Eden Pathing] Starting eden path playback...")
                self._run_eden_macro(eden_file)
            else:
                print("[Eden Pathing] Macro file not found: " + eden_file)
        except Exception as e:
            print(f"[Eden Pathing] ERROR: {e}")
            self.error_logging(e, "Error in perform_eden_path_sync")
        finally:
            print("[Eden Pathing] Path sequence finished.")
            self._eden_running = False
            self._eden_path_pending = False

    def perform_eden_contract_sync(self):
        if not self.detection_running or self.is_fishing_mode_enabled() or self.auto_pop_state: return
        self._eden_running = True
        try:
            print("[Eden] Performing contract...")
            contract_btn = self.config.get("eden_contract_button", [0, 0])

            for _ in range(4):
                if not self.detection_running: return
                pyautogui.press('e')
                time.sleep(0.3)

            for _ in range(7):
                if not self.detection_running: return
                if contract_btn and contract_btn[0] > 0 and contract_btn[1] > 0:
                    pyautogui.click(contract_btn[0], contract_btn[1])
                    print("[Eden] Clicked Eden contract button.")
                time.sleep(0.5)

            time.sleep(0.5)
        except Exception as e:
            self.error_logging(e, "Error in perform_eden_contract_sync")
        finally:
            self._eden_running = False

    def eden_contract_loop(self):
        last_contract_time = datetime.min
        last_path_time = datetime.min

        while self.detection_running:
            try:
                if self.config.get("enable_idle_mode", False):
                    time.sleep(2)
                    continue

                if getattr(self, "_eden_running", False):
                    time.sleep(2)
                    continue

                if self.is_fishing_mode_enabled() or getattr(self, "_egg_collecting", False) or getattr(self, "_potion_thread_active", False) or getattr(self, "_obby_running", False):
                    time.sleep(2)
                    continue

                go_to_eden = self.config.get("go_to_eden_spawn", False)
                auto_contract = self.config.get("auto_eden_contract", False)

                if not go_to_eden and not auto_contract:
                    time.sleep(2)
                    continue

                if (getattr(self, "_br_sc_running", False) or
                    getattr(self, "_mt_running", False) or
                    getattr(self, "auto_pop_state", False) or
                    getattr(self, "on_auto_merchant_state", False) or
                    getattr(self, "_auto_merchant_running", False) or
                    getattr(self, "_fishing_busy", False) or
                    self.reconnecting_state):
                    time.sleep(2)
                    continue

                current_biome = str(getattr(self, "current_biome", "") or "").upper().strip()
                if current_biome in ("GLITCHED", "DREAMSPACE", "CYBERSPACE"):
                    time.sleep(2)
                    continue

                if (getattr(self, "enable_potion_crafting_var", None)
                    and self.enable_potion_crafting_var.get()):
                    time.sleep(2)
                    continue

                if go_to_eden:
                    try:
                        path_interval = float(self.config.get("eden_path_interval", "35"))
                    except Exception:
                        path_interval = 35.0

                    if (datetime.now() - last_path_time) >= timedelta(minutes=path_interval):
                        print("[Eden] Starting periodic eden path sequence...")
                        self.perform_eden_path_sync()
                        last_path_time = datetime.now()
                        continue

                if auto_contract:
                    try:
                        interval_min = float(self.config.get("eden_contract_interval", "10"))
                    except Exception:
                        interval_min = 10.0

                    if (datetime.now() - last_contract_time) >= timedelta(minutes=interval_min):
                        self._action_scheduler.enqueue_action(self.perform_eden_contract_sync, name="eden_contract", priority=3)
                        last_contract_time = datetime.now()

                time.sleep(1)
            except Exception as e:
                self.error_logging(e, "Error in eden_contract_loop")
                time.sleep(1)

    def _potion_thread_launcher(self, *args, **kwargs):
        self._potion_thread_active = True
        try:
            self._potion_thread_launcher_impl(*args, **kwargs)
        finally:
            self._potion_thread_active = False

    def _potion_thread_launcher_impl(self, file_name, potions_directory="crafting_files_do_not_open", stop_after=None, cancel_if=None):
        try:
            final_name = file_name if file_name.endswith(".json") else f"{file_name}.json"
            path = os.path.join(os.getcwd(), potions_directory, final_name)
            if not os.path.exists(path):
                print(f"[Potion] File not found: {path}")
                return
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            self.error_logging(e, "Failed to load potion file")
            return

        events = data.get("events", [])
        if not events:
            return
        events.sort(key=lambda ev: ev.get("t", 0.0))

        potion_name = os.path.splitext(os.path.basename(final_name))[0]
        print(f"[Potion] Starting preparation sequence for {potion_name}")

        def _cancelled():
            try:
                if callable(cancel_if) and cancel_if():
                    return True
            except Exception:
                pass
            return (
                not self.detection_running
                or not self.enable_potion_crafting_var.get()
                or self.is_fishing_mode_enabled()
            )

        try:
            inventory_click_delay = int(self.config.get("inventory_click_delay", "0")) / 1000.0
            tab_pos = self.config.get("potion_items_tab", [0, 0])
            search_pos = self.config.get("potion_search_bar", [0, 0])
            first_slot_pos = self.config.get("potion_first_potion_slot_pos", [0, 0])
            auto_btn = self.config.get(
                "potion_auto_add_button",
                self.config.get("potion_auto_button", [0, 0]),
            )
            recipe_btn = self.config.get("potion_recipe_button", [0, 0])

            self.activate_roblox_window()
            time.sleep(0.5)

            for _ in range(4):
                if _cancelled(): return
                pyautogui.press('f')
                time.sleep(0.45)

            if tab_pos and tab_pos[0] > 0:
                for _ in range(5):
                    if _cancelled(): return
                    pyautogui.click(tab_pos[0], tab_pos[1])
                    time.sleep(0.3)

            if search_pos and search_pos[0] > 0:
                if _cancelled(): return
                pyautogui.click(search_pos[0], search_pos[1])
                time.sleep(0.6 + inventory_click_delay)
                pyautogui.hotkey('command', 'a') if sys.platform == 'darwin' else pyautogui.hotkey('ctrl', 'a')
                time.sleep(0.6 + inventory_click_delay)
                pyautogui.press('backspace')
                time.sleep(0.6 + inventory_click_delay)
                if potion_name:
                    self._safe_type_text(potion_name)
                    time.sleep(0.6 + inventory_click_delay)
                pyautogui.press('enter')
                time.sleep(1.5 + inventory_click_delay)

            if first_slot_pos and first_slot_pos[0] > 0:
                for _ in range(3):
                    if _cancelled(): return
                    pyautogui.click(first_slot_pos[0], first_slot_pos[1])
                    time.sleep(0.3)

            if auto_btn and auto_btn[0] > 0:
                if _cancelled(): return
                pyautogui.click(auto_btn[0], auto_btn[1])
                time.sleep(0.5)

            if recipe_btn and recipe_btn[0] > 0:
                if _cancelled(): return
                pyautogui.click(recipe_btn[0], recipe_btn[1])
                time.sleep(2.0)

        except Exception as e:
            self.error_logging(e, "Potion prep sequence failed")
            return

        overall_start = time.perf_counter()

        while not _cancelled():
            if stop_after is not None and time.perf_counter() - overall_start >= float(stop_after):
                print("[Potion] Switching interval reached. Stopping for next potion.")
                break

            loop_start = time.perf_counter()
            pressed_keys = set()
            print("[Potion] Starting loop iteration...")

            for ev in events:
                if _cancelled(): break
                if stop_after is not None and time.perf_counter() - overall_start >= float(stop_after):
                    break

                t = max(float(ev.get("t", 0.0)), 0.0)
                target_time = loop_start + t
                now = time.perf_counter()

                if target_time > now:
                    diff = target_time - now
                    if diff > 0.02:
                        sleep_ms = int((diff - 0.015) * 1000)
                        chunks = sleep_ms // 50
                        for _ in range(chunks):
                            if _cancelled(): break
                            if stop_after is not None and time.perf_counter() - overall_start >= float(stop_after):
                                break
                            time.sleep(0.05)
                        rem = (sleep_ms % 50) / 1000.0
                        if rem > 0:
                            time.sleep(rem)
                    while time.perf_counter() < target_time:
                        pass

                typ = ev.get("type", "")
                try:
                    if typ == "mouse_move":
                        pyautogui.moveTo(int(ev.get("x", 0)), int(ev.get("y", 0)))
                    elif typ == "mouse_down":
                        pyautogui.mouseDown(button=ev.get("button", "left"))
                    elif typ == "mouse_up":
                        pyautogui.mouseUp(button=ev.get("button", "left"))
                    elif typ == "mouse_wheel":
                        delta = int(ev.get("delta", 0))
                        if delta != 0:
                            pyautogui.scroll(delta)
                    elif typ == "key_down":
                        k = ev.get("key", "")
                        if k and k not in ("f1", "f2", "f3", "f4"):
                            pyautogui.keyDown(k)
                            pressed_keys.add(k)
                    elif typ == "key_up":
                        k = ev.get("key", "")
                        if k and k not in ("f1", "f2", "f3", "f4"):
                            pyautogui.keyUp(k)
                            pressed_keys.discard(k)
                except Exception:
                    pass

            if pressed_keys:
                print(f"[Potion] Releasing {len(pressed_keys)} stuck keys...")
                for k in list(pressed_keys):
                    try:
                        pyautogui.keyUp(k)
                    except Exception:
                        pass

            print("[Potion] Loop iteration finished.")
            time.sleep(0.1)

    def start_potion_crafting(self):
        if not hasattr(self, '_potion_gen'):
            self._potion_gen = 0
        self._potion_gen += 1
        my_gen = self._potion_gen

        def _potion_craft_loop():
            try:
                while self.detection_running and self._potion_gen == my_gen:
                    try:
                        if self.is_fishing_mode_enabled():
                            time.sleep(1)
                            continue
                        if not getattr(self, "enable_potion_crafting_var", None) or not self.enable_potion_crafting_var.get():
                            time.sleep(1)
                            continue

                        if (self.reconnecting_state or self.auto_pop_state or
                            self.on_auto_merchant_state or
                            self.current_biome in ("GLITCHED", "DREAMSPACE", "CYBERSPACE") or
                            getattr(self, '_mt_running', False) or
                            (getattr(self, '_egg_collecting', False) or getattr(self, '_eden_running', False) or getattr(self, '_potion_thread_active', False))):
                            time.sleep(2)
                            continue

                        if self.config.get("enable_idle_mode", False):
                            time.sleep(2)
                            continue

                        switching_enabled = self.config.get("enable_potion_switching", False)

                        if switching_enabled:
                            current_index = 0
                            slot_keys = [
                                "selected_potion_file",
                                "potion_file_1",
                                "potion_file_2",
                                "potion_file_3",
                            ]
                            while self.detection_running and self.enable_potion_crafting_var.get() and self._potion_gen == my_gen:
                                if not bool(self.config.get("enable_potion_switching", False)): break
                                interval = float(self.config.get("potion_switch_interval", "60"))
                                target_file = self.config.get(slot_keys[current_index], "").strip()

                                if not target_file or target_file.lower() == "none":
                                    print(f"[Potion] Slot #{current_index} is empty. Skipping.")
                                    current_index = (current_index + 1) % 4
                                    time.sleep(0.5)
                                    continue

                                print(f"[Potion] Starting Auto Craft: {target_file} (Index: {current_index})")
                                self._potion_thread_launcher(
                                    target_file,
                                    "crafting_files_do_not_open",
                                    stop_after=interval,
                                    cancel_if=lambda: not bool(self.config.get("enable_potion_switching", False)),
                                )
                                current_index = (current_index + 1) % 4
                        else:
                            file_name = self.config.get("selected_potion_file", "").strip()
                            if not file_name or file_name.lower() == "none":
                                time.sleep(2)
                                continue

                            print(f"[Potion] Starting Auto Craft: {file_name}")
                            self._potion_thread_launcher(
                                file_name,
                                cancel_if=lambda: bool(self.config.get("enable_potion_switching", False)),
                            )
                            self.config["potion_last_file"] = file_name
                            self.save_config()

                        time.sleep(0.5)

                    except Exception as e:
                        self.error_logging(e, "Error in potion craft loop iteration")
                        time.sleep(2)

            except Exception as e:
                self.error_logging(e, "Error in potion craft loop")

        threading.Thread(target=_potion_craft_loop, daemon=True).start()

    def glitch_effect(self):
        glitch_texts = [
            "GLITCHED", "GlItChEd", "gLiTcHeD", "GL1TCHED", "g#lt#c%",
            "g!olitc3", "g$&*ct", "G1iTcHeD", "gL1tCh3d", "gL!tCh3d",
            "G1!tCh3D", "gL1tCh3D", "gL!tCh3D", "G1!tCh3d", "gL1tCh3d"]

        glitch_colors = [
            "#FF0000", "#00FF00", "#0000FF", "#FFFF00", "#FF00FF",
            "#00FFFF", "#a6c9a3", "#ff69b4", "#8a2be2", "#7fff00",
            "#d2691e", "#ff7f50", "#6495ed", "#dc143c", "#00ced1"
        ]

        def update_glitch():
            glitchy_ahh_text = random.choice(glitch_texts)
            color = random.choice(glitch_colors)
            self.stats_labels["GLITCHED"].config(text=f"{glitchy_ahh_text}: {self.biome_counts['GLITCHED']}",
                                                 foreground=color)
            self.root.after(25, update_glitch)

        update_glitch()

    def update_stats(self):
        total_biomes = sum(self.biome_counts.values())

        if hasattr(self, "stats_labels"):
            for biome, label in self.stats_labels.items():
                try:
                    label.config(text=f"{biome}: {self.biome_counts[biome]}")
                except Exception:
                    pass

        if hasattr(self, "total_biomes_label"):
            try:
                self.total_biomes_label.config(text=f"Total Biomes Found: {total_biomes}", foreground="light green")
            except Exception:
                pass

        if hasattr(self, "session_label"):
            try:
                self.session_label.config(text=f"Running Session: {self.get_total_session_time()}")
            except Exception:
                pass

        self.save_config()

        if hasattr(self, "on_stats_update") and callable(self.on_stats_update):
            try:
                self.on_stats_update()
            except Exception:
                pass

    def format_seconds_to_hhmmss(self, total_seconds):
        total_seconds = int(total_seconds)
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02}:{minutes:02}:{seconds:02}"

    def update_coordinates(self, config_key, region, coord_vars):
        x, y = region[0], region[1]
        coord_vars[config_key][0].set(x)
        coord_vars[config_key][1].set(y)
        self.save_config()

    def validate_and_save_ps_link(self):
        private_server_link = self.private_server_link_entry.get()
        if not self.validate_private_server_link(private_server_link):
            messagebox.showwarning(
                "Invalid PS Link!",
                "The link you provided is not a valid Roblox link. It could be either a share link or a private server code link. "
                "Please ensure the link is correct and try again.\n\n"
                "Valid links should look like:\n"
                "- Share link: https://www.roblox.com/share?code=1234567899abcdefxyz&type=Server\n"
                "- Private server code link: https://www.roblox.com/games/15532962292/Sols-RNG?privateServerLinkCode=xxxxxxxx"
            )
            return

        self.save_config()

    def validate_private_server_link(self, link):
        try:
            from urllib.parse import parse_qs, urlparse

            raw_link = str(link or "").strip()
            if not raw_link:
                return False

            if re.search(r"privateserverlinkcode=", raw_link, flags=re.IGNORECASE):
                return True

            parsed = urlparse(raw_link)
            if parsed.scheme not in ("http", "https"):
                return False

            host = (parsed.netloc or "").lower()
            if host not in ("roblox.com", "www.roblox.com"):
                return False

            path = parsed.path or ""
            query = parse_qs(parsed.query)
            query_ci = {str(k).strip().lower(): v for k, v in query.items()}

            if query_ci.get("privateserverlinkcode") and str(query_ci["privateserverlinkcode"][0]).strip():
                return True

            if path.startswith("/share"):
                has_code = bool(query_ci.get("code") and str(query_ci["code"][0]).strip())
                link_type = str(query_ci.get("type", [""])[0]).strip().lower()
                return has_code and link_type in ("", "server")

            return False
        except Exception:
            return False

    def _build_reconnect_deep_links(self, link):
        try:
            from urllib.parse import parse_qs, quote, urlparse

            raw_link = str(link or "").strip()
            if not raw_link:
                return []

            parsed = urlparse(raw_link)
            query = parse_qs(parsed.query)
            query_ci = {str(k).strip().lower(): v for k, v in query.items()}
            path = parsed.path or ""
            is_roblox_protocol = parsed.scheme.lower() == "roblox"
            path_l = path.lower()
            raw_l = raw_link.lower()

            # roblox://placeID=...&linkCode=... does not parse query normally
            raw_place_match = re.search(r"placeID=(\d+)", raw_link, flags=re.IGNORECASE)
            raw_place_id = raw_place_match.group(1) if raw_place_match else ""

            place_match = re.search(r"/games/(\d+)", path, flags=re.IGNORECASE)
            place_id = place_match.group(1) if place_match else (raw_place_id or "15532962292")

            link_code = ""
            source_type = ""
            if query_ci.get("privateserverlinkcode"):
                link_code = str(query_ci["privateserverlinkcode"][0]).strip()
                source_type = "private"
            elif query_ci.get("linkcode"):
                link_code = str(query_ci["linkcode"][0]).strip()
                source_type = "private"
            elif query_ci.get("code"):
                link_type = str(query_ci.get("type", [""])[0]).strip().lower()
                if link_type in ("", "server"):
                    link_code = str(query_ci["code"][0]).strip()
                    source_type = "share"

            # Backward-compat support for old raw format:
            # Sols-RNG?privateServerLinkCode=xxxxxxxx
            if not link_code:
                m = re.search(r"privateServerLinkCode=([^&\s]+)", raw_link, flags=re.IGNORECASE)
                if m:
                    link_code = str(m.group(1)).strip()
                    source_type = "private"
            if not link_code:
                m = re.search(r"linkCode=([^&\s]+)", raw_link, flags=re.IGNORECASE)
                if m:
                    link_code = str(m.group(1)).strip()
                    source_type = "private"
            if not link_code:
                m = re.search(r"code=([^&\s]+)", raw_link, flags=re.IGNORECASE)
                if m:
                    link_code = str(m.group(1)).strip()
                    if "navigation/share_links" in raw_l or path_l.startswith("/share"):
                        source_type = "share"

            # Keep explicit roblox:// input as the first launch candidate.
            candidates = []
            if is_roblox_protocol:
                candidates.append(raw_link)

            if not link_code:
                return candidates

            encoded_code = quote(link_code, safe="")
            share_deep_link = f"roblox://navigation/share_links?code={encoded_code}&type=Server"
            private_deep_link = f"roblox://placeID={place_id}&linkCode={encoded_code}"
            if source_type == "private":
                candidates.extend([private_deep_link, share_deep_link])
            else:
                candidates.extend([share_deep_link, private_deep_link])

            deduped = []
            for candidate in candidates:
                if candidate not in deduped:
                    deduped.append(candidate)
            return deduped
        except Exception:
            return []

    def _enqueue_player_embed(self, embed):
        if not hasattr(self, "player_log_queue") or self.player_log_queue is None:
            try:
                self.player_log_queue = queue.Queue()
            except Exception:
                return
        try:
            self.player_log_queue.put(embed)
        except Exception:
            pass

    def _parse_iso_ts(self, s):
        try:
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            return datetime.fromisoformat(s)
        except:
            return datetime.now(timezone.utc)

    def check_roblox_procs(self):
        try:
            current_user = psutil.Process().username()
            current_user_norm = str(current_user or "").strip().lower()
            running_processes = psutil.process_iter(['pid', 'name', 'username'])
            roblox_processes = []

            for proc in running_processes:
                proc_name = str(proc.info.get('name') or "")
                # macOS process names
                if proc_name not in ['RobloxPlayerBeta', 'RobloxPlayer', 'RobloxApp']:
                    continue

                proc_user_norm = str(proc.info.get('username') or "").strip().lower()
                if current_user_norm and proc_user_norm and proc_user_norm != current_user_norm:
                    continue

                roblox_processes.append(proc.info)

            if roblox_processes:
                return True

        except Exception as e:
            self.error_logging(e, "Error in check_roblox_procs function.")

        return False

    def terminate_roblox_processes(self):
        try:
            current_user = psutil.Process().username()
            current_user_norm = str(current_user or "").strip().lower()
            running_processes = psutil.process_iter(['pid', 'name', 'username'])
            target_procs = ['RobloxPlayerBeta', 'RobloxPlayer', 'RobloxApp', 'RobloxCrashHandler']

            for proc in running_processes:
                try:
                    proc_name = str(proc.info.get('name') or "")
                    if proc_name not in target_procs: continue
                    proc_user_norm = str(proc.info.get('username') or "").strip().lower()
                    if current_user_norm and proc_user_norm and proc_user_norm != current_user_norm: continue
                    print(f"Terminating process: {proc_name} (PID: {proc.info.get('pid')})")
                    try:
                        proc.kill()
                        proc.wait(timeout=3)
                    except psutil.TimeoutExpired:
                        pass
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass

        except Exception as e:
            self.error_logging(e, "Error in terminate_roblox_processes function.")

    def perform_periodic_inventory_screenshot_sync(self):
        try:
            if self.config.get("enable_idle_mode", False): return
            if self._is_fishing_blocked(): return
            if getattr(self, "enable_potion_crafting_var", None) and self.enable_potion_crafting_var.get(): return
            if not getattr(self, "periodical_inventory_var", None) or not self.periodical_inventory_var.get(): return
            if not self.detection_running or self.reconnecting_state: return
            try:
                interval_min = float(self.periodical_inventory_interval_var.get())
            except Exception:
                interval_min = 5.0
            if (datetime.now() - getattr(self, "last_inventory_screenshot_time", datetime.min)) < timedelta(minutes=interval_min):
                return
            if not self.check_roblox_procs(): return
            for _ in range(4):
                if not self.detection_running or self._is_fishing_blocked() or self.auto_pop_state or (getattr(self, "_egg_collecting", False) or getattr(self, "_eden_running", False) or getattr(self, "_potion_thread_active", False)):
                    return
                if not self._sleep_with_cancel(0.8):
                    return
            search_bar = self.config.get("search_bar", [855, 358])
            inventory_menu = self.config.get("inventory_menu", [36, 535])
            items_tab = self.config.get("items_tab", [1272, 329])
            inventory_close_button = self.config.get("inventory_close_button", [1418, 298])
            if inventory_menu and inventory_menu[0]:
                pyautogui.click(inventory_menu[0], inventory_menu[1])
                if not self._sleep_with_cancel(0.35):
                    return
            if items_tab and items_tab[0]:
                pyautogui.click(items_tab[0], items_tab[1])
                if not self._sleep_with_cancel(1):
                    return
                pyautogui.click(search_bar[0], search_bar[1])
                if not self._sleep_with_cancel(0.35):
                    return
            try:
                screenshot_dir = os.path.join(os.getcwd(), "images")
                os.makedirs(screenshot_dir, exist_ok=True)
                filename = os.path.join(screenshot_dir, f"inventory_screenshot_{int(time.time())}.png")
                try:
                    img = pyautogui.screenshot()
                except subprocess.CalledProcessError:
                    self.append_log(
                        "[Screenshot] ERROR: macOS denied screen capture. "
                        "Go to System Settings \u2192 Privacy & Security \u2192 Screen Recording "
                        "and enable access for this app, then restart."
                    )
                    return
                img.save(filename)
                self.send_inventory_screenshot_webhook(filename)
                self.last_inventory_screenshot_time = datetime.now()
            except Exception as e:
                self.error_logging(e, "Error taking/sending inventory screenshot")
            try:
                if inventory_close_button and inventory_close_button[0]:
                    pyautogui.click(inventory_close_button[0], inventory_close_button[1])
                    self._sleep_with_cancel(0.22)
            except Exception as e:
                self.error_logging(e, "Error while closing inventory after screenshot")
        except Exception as e:
            self.error_logging(e, "Error in perform_periodic_inventory_screenshot_sync")

    def Global_MouseClick(self, x, y, click=1):
        time.sleep(0.335)
        pyautogui.click(x, y, clicks=click, button='left')

    def use_portable_crack(self):
        try:
            self._action_scheduler.enqueue_action(self._teleport_crack_impl, name="teleport_crack", priority=8)
        except Exception:
            try:
                self._teleport_crack_impl()
            except Exception:
                pass

    def _teleport_crack_impl(self, ignore_eden=False):
        self._portable_crack_running = True
        fishing_override = bool(getattr(self, "_fishing_br_sc_override", False))
        try:
            def _cancelled():
                if fishing_override:
                    return (
                        not self.detection_running
                        or self.reconnecting_state
                    )
                return (
                    not self.detection_running
                    or self.reconnecting_state
                    or self.auto_pop_state
                    or self.on_auto_merchant_state
                    or (self.is_fishing_mode_enabled() if ignore_eden else self._is_fishing_blocked())
                    or self.config.get("enable_potion_crafting")
                    or (getattr(self, "_egg_collecting", False) or (not ignore_eden and getattr(self, "_eden_running", False)) or getattr(self, "_potion_thread_active", False))
                    or (getattr(self, "enable_potion_crafting_var", None) and self.enable_potion_crafting_var.get())
                )

            def _do_sleep(seconds):
                if fishing_override or ignore_eden:
                    time.sleep(max(0.0, seconds))
                    return not _cancelled()
                return self._sleep_with_cancel(seconds)

            if _cancelled(): return
            if not _do_sleep(1.3): return

            inventory_click_delay = int(self.config.get("inventory_click_delay", "0")) / 1000.0
            inventory_menu = self.config.get("inventory_menu", [36, 535])
            items_tab = self.config.get("items_tab", [1272, 329])
            search_bar = self.config.get("search_bar", [855, 358])
            first_item_slot = self.config.get("first_item_inventory_slot_pos", [845, 460])
            amount_box = self.config.get("amount_box", [594, 570])
            use_button = self.config.get("use_button", [710, 573])
            inventory_close_button = self.config.get("inventory_close_button", [1418, 298])

            for _ in range(3):
                if _cancelled(): return
                if not _do_sleep(0.15): return

            self.append_log("Using Portable Crack")

            self.Global_MouseClick(inventory_menu[0], inventory_menu[1])
            if not _do_sleep(0.2 + inventory_click_delay): return
            self.Global_MouseClick(items_tab[0], items_tab[1])
            if not _do_sleep(0.23): return
            self.Global_MouseClick(items_tab[0], items_tab[1])
            if not _do_sleep(0.23): return
            self.Global_MouseClick(search_bar[0], search_bar[1])
            if not _do_sleep(0.2 + inventory_click_delay): return
            if _cancelled(): return

            self.Global_MouseClick(search_bar[0], search_bar[1])
            if not _do_sleep(0.23): return
            self.Global_MouseClick(search_bar[0], search_bar[1])
            if not _do_sleep(0.23): return
            self.Global_MouseClick(search_bar[0], search_bar[1])
            if not _do_sleep(0.2 + inventory_click_delay): return
            if _cancelled(): return
            self._safe_type_text("crack")
            if not _do_sleep(0.4 + inventory_click_delay): return
            self.Global_MouseClick(first_item_slot[0], first_item_slot[1])
            if not _do_sleep(0.4 + inventory_click_delay): return
            try:
                if not self._ocr_first_slot_matches("crack"):
                    self.Global_MouseClick(inventory_close_button[0], inventory_close_button[1])
                    _do_sleep(0.15 + inventory_click_delay)
                    return
            except Exception:
                pass
            self.Global_MouseClick(first_item_slot[0], first_item_slot[1])
            if not _do_sleep(0.4 + inventory_click_delay): return
            self.Global_MouseClick(first_item_slot[0], first_item_slot[1])
            if not _do_sleep(0.3 + inventory_click_delay): return

            if _cancelled(): return
            self.Global_MouseClick(amount_box[0], amount_box[1])
            if not _do_sleep(0.16 + inventory_click_delay): return
            pyautogui.hotkey('command', 'a') if sys.platform == 'darwin' else pyautogui.hotkey('ctrl', 'a')
            if not _do_sleep(0.13 + inventory_click_delay): return
            pyautogui.press('backspace')
            if not _do_sleep(0.13 + inventory_click_delay): return
            self._safe_type_text('1')
            if not _do_sleep(0.13 + inventory_click_delay): return

            if _cancelled(): return
            self.Global_MouseClick(use_button[0], use_button[1])
            if not _do_sleep(0.22 + inventory_click_delay): return

            if _cancelled(): return
            self.Global_MouseClick(inventory_close_button[0], inventory_close_button[1])
            _do_sleep(0.22 + inventory_click_delay)

        except Exception as e:
            self.error_logging(e, "Error in _teleport_crack_impl function.")
        finally:
            self._portable_crack_running = False

    def use_br_sc(self, item_name):
        try:
            self._action_scheduler.enqueue_action(lambda: self._use_br_sc_impl(item_name), name=f"use_br_sc:{item_name}", priority=6)
        except Exception:
            try:
                self._use_br_sc_impl(item_name)
            except Exception:
                pass

    def _use_br_sc_impl(self, item_name):
        self._br_sc_running = True
        fishing_override = bool(getattr(self, "_fishing_br_sc_override", False))
        _inventory_opened = False
        try:
            def _cancelled():
                if fishing_override:
                    return (
                        not self.detection_running
                        or self.reconnecting_state
                    )
                return (
                    not self.detection_running
                    or self.reconnecting_state
                    or self.auto_pop_state
                    or self.on_auto_merchant_state
                    or self._is_fishing_blocked()
                    or self.config.get("enable_potion_crafting")
                    or self.current_biome in ("GLITCHED", "DREAMSPACE", "CYBERSPACE")
                    or getattr(self, "_mt_running", False)
                    or (getattr(self, "_egg_collecting", False) or getattr(self, "_eden_running", False) or getattr(self, "_potion_thread_active", False))
                    or (getattr(self, "enable_potion_crafting_var", None) and self.enable_potion_crafting_var.get())
                )

            # When called from fishing loop
            def _do_sleep(seconds):
                if fishing_override:
                    time.sleep(max(0.0, seconds))
                    return not _cancelled()
                return self._sleep_with_cancel(seconds)

            if _cancelled():
                return
            if not _do_sleep(1.3):
                return

            inventory_click_delay = int(self.config.get("inventory_click_delay", "0")) / 1000.0
            inventory_menu = self.config.get("inventory_menu", [36, 535])
            items_tab = self.config.get("items_tab", [1272, 329])
            search_bar = self.config.get("search_bar", [855, 358])
            first_item_slot = self.config.get("first_item_inventory_slot_pos", [845, 460])
            amount_box = self.config.get("amount_box", [594, 570])
            use_button = self.config.get("use_button", [710, 573])
            inventory_close_button = self.config.get("inventory_close_button", [1418, 298])

            for _ in range(5):
                if _cancelled():
                    return
                if not _do_sleep(0.15):
                    return

            print(f"Using {item_name.capitalize()}")

            self.Global_MouseClick(inventory_menu[0], inventory_menu[1])
            _inventory_opened = True
            if not _do_sleep(0.2 + inventory_click_delay):
                return
            self.Global_MouseClick(items_tab[0], items_tab[1])
            if not _do_sleep(0.23):
                return
            self.Global_MouseClick(items_tab[0], items_tab[1])
            if not _do_sleep(0.23):
                return
            self.Global_MouseClick(search_bar[0], search_bar[1])
            if not _do_sleep(0.2 + inventory_click_delay):
                return
            if _cancelled():
                return

            self.Global_MouseClick(search_bar[0], search_bar[1])
            if not _do_sleep(0.23):
                return
            self.Global_MouseClick(search_bar[0], search_bar[1])
            if not _do_sleep(0.23):
                return
            self.Global_MouseClick(search_bar[0], search_bar[1])
            if not _do_sleep(0.2 + inventory_click_delay):
                return
            if _cancelled():
                return
            self._safe_type_text(item_name)
            if not _do_sleep(0.4 + inventory_click_delay):
                return
            self.Global_MouseClick(first_item_slot[0], first_item_slot[1])
            if not _do_sleep(0.4 + inventory_click_delay):
                return
            try:
                if not self._ocr_first_slot_matches(item_name):
                    inventory_close_button = self.config.get("inventory_close_button", [1418, 298])
                    self.Global_MouseClick(inventory_close_button[0], inventory_close_button[1])
                    _do_sleep(0.15 + inventory_click_delay)
                    return
            except Exception:
                pass
            self.Global_MouseClick(first_item_slot[0], first_item_slot[1])
            if not _do_sleep(0.4 + inventory_click_delay):
                return
            self.Global_MouseClick(first_item_slot[0], first_item_slot[1])
            if not _do_sleep(0.3 + inventory_click_delay):
                return
            if _cancelled():
                return
            self.Global_MouseClick(amount_box[0], amount_box[1])
            if not _do_sleep(0.16 + inventory_click_delay):
                return
            pyautogui.hotkey('command', 'a') if sys.platform == 'darwin' else pyautogui.hotkey('ctrl', 'a')
            if not _do_sleep(0.13 + inventory_click_delay):
                return
            pyautogui.press('backspace')
            if not _do_sleep(0.13 + inventory_click_delay):
                return
            self._safe_type_text('1')
            if not _do_sleep(0.13 + inventory_click_delay):
                return

            if _cancelled():
                return
            self.Global_MouseClick(use_button[0], use_button[1])
            if not _do_sleep(0.22 + inventory_click_delay):
                return

            if _cancelled():
                return
            self.Global_MouseClick(inventory_close_button[0], inventory_close_button[1])
            _do_sleep(0.22 + inventory_click_delay)
            _inventory_opened = False

        except Exception as e:
            self.error_logging(e, "Error in use_br_sc function.")
        finally:
            if _inventory_opened:
                try:
                    _inv_close = self.config.get("inventory_close_button", [1418, 298])
                    self.Global_MouseClick(_inv_close[0], _inv_close[1])
                    time.sleep(0.35)
                except Exception:
                    pass
            self._br_sc_running = False

    def Merchant_Handler(self):
        try:
            fishing_override = bool(getattr(self, "_fishing_br_sc_override", False))
            def _cancelled():
                if fishing_override:
                    return (
                        not self.detection_running
                        or self.reconnecting_state
                    )
                return (
                    not self.detection_running
                    or self.reconnecting_state
                    or self.auto_pop_state
                    or self._is_fishing_blocked()
                    or self.config.get("enable_potion_crafting")
                    or (getattr(self, "_egg_collecting", False) or getattr(self, "_eden_running", False) or getattr(self, "_potion_thread_active", False))
                    or self.current_biome in ("GLITCHED", "DREAMSPACE", "CYBERSPACE")
                )

            if _cancelled():
                return False

            self.on_auto_merchant_state = True
            merchant_name_ocr_pos = self.config["merchant_name_ocr_pos"]
            merchant_open_button = self.config["merchant_open_button"]
            first_item_slot_pos = self.config.get("first_item_merchant_slot_pos", [954, 696])
            item_name_ocr_pos = self.config["item_name_ocr_pos"]
            merchant_dialogue_box = self.config["merchant_dialogue_box"]
            merchant_extra_slot = int(self.config.get("merchant_extra_slot", "0"))

            merchant_name = ""
            ocrMisdetect_Key = {
                "heavenly potion": "heavenly potion",
                "rune of galaxy": "rune of galaxy",
                "rune of rainstorm": "rune of rainstorm",
                "strange potion": "strange potion",
                "stella's candle": "stella's candle",
                "merchant tracker": "merchant tracker",
                "random potion sack": "random potion sack",
                "gear a": "gear a",
                "Genr A": "gear a",
                "gear b": "gear b",
                "lucky potion": "lucky potion",
                "void coin": "void coin",
                "lucky penny": "lucky penny",
                "mixed potion": "mixed potion",
                "lucky potion l": "lucky potion l",
                "lucky potion xl": "lucky potion xl",
                "speed potion": "speed potion",
                "speed potion l": "speed potion l",
                "speed potion xl": "speed potion xl",
                "oblivion potion": "oblivion potion",
                "potion of bound": "potion of bound",
                "rune of everything": "rune of everything",
                "rune of dust": "rune of dust",
                "rune of nothing": "rune of nothing",
                "rune of corruption": "rune of corruption",
                "rune of hell": "rune of hell",
                "rune of frost": "rune of frost",
                "rune of wind": "rune of wind"
            }

            if not hasattr(self, 'last_merchant_interaction'):
                self.last_merchant_interaction = 0

            if not hasattr(self, 'last_merchant_sent'):
                self.last_merchant_sent = {}

            merchant_cooldown_time = 300
            current_time = time.time()

            if current_time - self.last_merchant_interaction < merchant_cooldown_time:
                return False

            for _ in range(6):
                if _cancelled():
                    return
                pyautogui.press('e')
                if not self._sleep_with_cancel(0.55):
                    return

            if not self._sleep_with_cancel(0.65):
                return

            # Click through merchant dialogue (no hold)
            for _ in range(8):
                if _cancelled():
                    return
                self._mouse_click(merchant_dialogue_box[0], merchant_dialogue_box[1], clicks=2)
                if not self._sleep_with_cancel(0.55):
                    return

            for _ in range(6):
                if _cancelled():
                    return

                x, y, w, h = merchant_name_ocr_pos
                merchant_name_text = self.extract_text_with_easyocr((x, y, w, h)).strip()

                mari_candidates = ["Mari", "Mori", "Marl", "Mar1", "MarI", "Mar!", "Maori"]
                jester_candidates = ["Jester", "Dester", "Jostor", "Jestor", "Joster", "Destor", "Doster", "Dostor", "jester", "dester"]
                rin_candidates = ["Rin", "R1n", "R1N", "RIN", "RiN"]
                try:
                    if fuzzy_match_any(merchant_name_text, mari_candidates, threshold=0.75):
                        merchant_name = "Mari"
                        print("[Merchant Detection]: Mari name found!")
                        break
                    elif fuzzy_match_any(merchant_name_text, jester_candidates, threshold=0.75):
                        merchant_name = "Jester"
                        print("[Merchant Detection]: Jester name found!")
                        break
                    elif fuzzy_match_any(merchant_name_text, rin_candidates, threshold=0.75):
                        merchant_name = "Rin"
                        print("[Merchant Detection]: Rin name found!")
                        break
                except Exception as e:
                    try:
                        if any(name in merchant_name_text for name in mari_candidates):
                            merchant_name = "Mari"
                            print("[Merchant Detection - fallback]: Mari name found!")
                            break
                        if any(name in merchant_name_text for name in jester_candidates):
                            merchant_name = "Jester"
                            print("[Merchant Detection - fallback]: Jester name found!")
                            break
                        if any(name in merchant_name_text for name in rin_candidates):
                            merchant_name = "Rin"
                            print("[Merchant Detection - fallback]: Rin name found!")
                            break
                    except Exception:
                        pass

                if not self._sleep_with_cancel(0.12):
                    return

            if merchant_name:
                last_sent_time = self.last_merchant_sent.get((merchant_name, 'ocr'), 0)
                if current_time - last_sent_time < merchant_cooldown_time:
                    print(f"Merchant {merchant_name} already sent recently lol")
                    return False

                print(f"Opening merchant interface for {merchant_name}")

                x, y = merchant_open_button
                self._mouse_click(x, y, clicks=3)
                inventory_click_delay = int(self.config.get("inventory_click_delay", "0")) / 1000.0
                if not self._sleep_with_cancel(7 + inventory_click_delay):
                    return

                screenshot_dir = os.path.join(os.getcwd(), "images")
                os.makedirs(screenshot_dir, exist_ok=True)

                item_screenshot = pyautogui.screenshot()
                screenshot_path = os.path.join(screenshot_dir,
                                               f"merchant_{merchant_name.lower()}_{int(current_time)}.png")
                item_screenshot.save(screenshot_path)

                self.send_merchant_webhook(merchant_name, screenshot_path, source='ocr')
                self.last_merchant_sent[(merchant_name, 'ocr')] = current_time

                if "merchant_counts" not in self.config:
                    self.config["merchant_counts"] = {"Jester": 0, "Mari": 0, "Rin": 0}
                self.config["merchant_counts"][merchant_name] = self.config["merchant_counts"].get(merchant_name, 0) + 1
                self.save_config()
                self.append_log(f"[Merchant Detection] {merchant_name} count: {self.config['merchant_counts'][merchant_name]}")

                auto_buy_items = self.config.get(f"{merchant_name}_Items", {})
                if not isinstance(auto_buy_items, dict):
                    auto_buy_items = {}
                purchased_items = {}

                total_slots = 5 + merchant_extra_slot
                for slot_index in range(total_slots):
                    if _cancelled():
                        return

                    x, y = first_item_slot_pos
                    slot_x = x + (slot_index * 193)
                    self._mouse_click(slot_x, y, clicks=2)
                    if not self._sleep_with_cancel(0.15):
                        return

                    x, y, w, h = item_name_ocr_pos
                    item_text = self.extract_text_with_easyocr((x, y, w, h)).strip().lower()

                    self.append_log(f"[Merchant Detection - {merchant_name}] Detected item text: {item_text}")

                    corrected_item_name = item_text.split('|')[0].strip()
                    corrected_candidate = fuzzy_correct_item_name(corrected_item_name, ocrMisdetect_Key, threshold=0.6)
                    if isinstance(corrected_candidate, str) and corrected_candidate != corrected_item_name:
                        print(f"Corrected OCR misdetection: '{item_text}' -> '{corrected_candidate}'")
                        corrected_item_name = corrected_candidate
                    else:
                        for misdetect, correct in ocrMisdetect_Key.items():
                            try:
                                if misdetect in corrected_item_name.lower():
                                    corrected_item_name = correct
                                    print(f"Corrected OCR misdetection (fallback): '{item_text}' -> '{correct}'")
                                    break
                            except Exception:
                                pass

                    print(f"Detected item text: {item_text} | Corrected: {corrected_item_name}")

                    for item_name, item_vals in auto_buy_items.items():
                        enabled = item_vals[0] if len(item_vals) > 0 else False
                        quantity = int(item_vals[1]) if len(item_vals) > 1 else 1

                        if enabled and corrected_item_name == item_name.lower():
                            purchased_count = purchased_items.get(item_name, 0)

                            if purchased_count == 0:
                                self.append_log(
                                    f"[Merchant Detection - {merchant_name}] - Item {item_name} found. Proceeding to buy {quantity}")

                                purchase_amount_button = self.config["purchase_amount_button"]
                                purchase_button = self.config["purchase_button"]

                                self._mouse_click(*purchase_amount_button)
                                self._safe_type_text(str(quantity))
                                if not self._sleep_with_cancel(0.23):
                                    return

                                self._mouse_click(*purchase_button, clicks=3)
                                if not self._sleep_with_cancel(3.67):
                                    return

                                purchased_items[item_name] = purchased_count + 1
                                break

                merchant_close_button = self.config.get("merchant_close_button", [1086, 342])
                self._mouse_click(merchant_close_button[0], merchant_close_button[1], clicks=3)
                self.last_merchant_interaction = current_time
                return True
            else:
                merchant_close_button = self.config.get("merchant_close_button", [1086, 342])
                self.Global_MouseClick(merchant_close_button[0], merchant_close_button[1], click=3)
                if not self._sleep_with_cancel(0.67): return False
                self.Global_MouseClick(merchant_open_button[0], merchant_open_button[1], click=3)
                return False

        except Exception as e:
            self.error_logging(e,
                               "Error in Merchant_Handler function \n (If it say valueError: not enough values to unpack (expect 3 got 2) then open both mari and jester setting and click save selection again!)")
            return False
        finally:
            self.on_auto_merchant_state = False

    def _ocr_first_slot_matches(self, expected):
        if not self.config.get("enable_ocr_failsafe", False):
            return True
        ocr_pos = self.config.get("first_item_slot_ocr_pos", [0, 0, 80, 80])
        try:
            x, y, w, h = int(ocr_pos[0]), int(ocr_pos[1]), int(ocr_pos[2]), int(ocr_pos[3])
            img = pyautogui.screenshot(region=(x, y, w, h))
            text = self.extract_text_with_easyocr((x, y, w, h)).strip().lower()
            self.append_log(f"[DEBUG] ocr item first slot failsafe: '{text}'")
        except Exception as e:
            text = ""
            self.append_log(f"[DEBUG] ocr item first slot failsafe exception: {e}")
        expected_lower = (expected or "").lower()
        if expected_lower and expected_lower in text:
            return True
        tokens = re.findall(r'\w{4,}', expected_lower)
        for t in tokens:
            if t in text:
                return True
        try:
            threshold = float(self.config.get("ocr_failsafe_match_threshold", 0.7))
        except Exception:
            threshold = 0.7
        threshold = max(0.0, min(1.0, threshold))
        candidates = [expected_lower] if expected_lower else []
        candidates.extend(tokens)
        if candidates and fuzzy_match_any(text, candidates, threshold=threshold):
            return True
        return False

    def close_chat_if_open(self, force=False):
        try:
            if not force and not self.config.get("auto_chat_close", False): return

            chat_hover = self.config.get("chat_hover_pos", [272, 252])
            chat_ocr_region = self.config.get("chat_tab_ocr_pos", [341, 83, 210, 40])
            chat_close = self.config.get("chat_close_button", [174, 40])

            if not (chat_hover and chat_hover[0] and chat_close and chat_close[0]):
                self.append_log("[WinOcr] You haven't calibrated chat failsafe so auto close chat will not running (WARNING)")
                return

            for _ in range(3):
                self.activate_roblox_window()
                time.sleep(0.2)

            sw = pyautogui.size()
            pyautogui.moveTo(sw.width // 2, sw.height // 2)
            time.sleep(0.85)
            pyautogui.moveTo(chat_hover[0], chat_hover[1])
            time.sleep(0.85)

            chat_detected = False
            for attempt in range(1, 4):
                tab_text = self.extract_text_with_easyocr(tuple(chat_ocr_region)).lower()
                self.append_log(f"[WinOcr] Close Chat OCR Check ({attempt}/3): '{tab_text}'")

                if fuzzy_match_any(tab_text, ["general", "server message"], threshold=0.75):
                    chat_detected = True
                    break

                if attempt < 3:
                    time.sleep(0.45)

            if chat_detected:
                self.append_log("[WinOcr] Chat is open! Closing it...")
                pyautogui.click(chat_close[0], chat_close[1])
                time.sleep(0.45)
            else:
                self.append_log("[WinOcr] Chat already closed! Skipping...")

        except Exception as e:
            self.error_logging(e, "close_chat_if_open error")

    def activate_roblox_window(self):
        try:
            script = '''
            tell application "System Events"
                set frontmost of process "Roblox" to true
            end tell
            '''
            subprocess.run(["osascript", "-e", script], check=False)
        except Exception:

            pass

    def perform_anti_afk_action(self):
        try:
            if not getattr(self, "anti_afk_var", None) or not self.anti_afk_var.get():
                return
            if not self.detection_running:
                return
            self.activate_roblox_window()
            pyautogui.press('space')
            self.append_log("[Anti-AFK] Pressed spacebar.")
        except Exception as e:
            self.error_logging(e, "Error in anti-afk action")

    def anti_afk_loop(self):
        while self.detection_running:
            try:
                interval_min = float(self.anti_afk_interval_var.get())
            except Exception:
                interval_min = 5.0

            interval_min = max(1.0, min(20.0, interval_min))
            interval_sec = interval_min * 60.0

            time.sleep(interval_sec)

            if not self.detection_running:
                break
            try:
                if self.is_fishing_mode_enabled():
                    continue
                if (getattr(self, "_egg_collecting", False) or getattr(self, "_eden_running", False) or getattr(self, "_potion_thread_active", False)):
                    continue
                self.perform_anti_afk_action()
            except Exception as e:
                try:
                    self.error_logging(e, "Error in anti_afk_loop")
                except Exception:
                    pass

    def get_scaled_coordinates(self, original_x, original_y):
        original_width = 1920
        original_height = 1080
        current_width, current_height = pyautogui.size()

        x_scale = current_width / original_width
        y_scale = current_height / original_height
        return int(original_x * x_scale), int(original_y * y_scale)

    def _get_auto_pop_biome_entry(self, biome_name):
        try:
            all_biomes = self.config.get("auto_pop_biomes", {})
            if not isinstance(all_biomes, dict):
                return {"enabled": False, "buffs": {}}
            entry = all_biomes.get(biome_name, {})
            if not isinstance(entry, dict):
                return {"enabled": False, "buffs": {}}
            buffs = entry.get("buffs", {})
            if not isinstance(buffs, dict):
                buffs = {}
            return {
                "enabled": bool(entry.get("enabled", False)),
                "buffs": buffs,
            }
        except Exception:
            return {"enabled": False, "buffs": {}}

    def _build_auto_pop_buffs_to_use(self, buff_config):
        buffs_to_use = []
        priority_order = [
            "Xyz Potion",
            "Transcendent Potion",
            "Warp Potion",
            "Rune of Everything",
            "Heavenly Potion",
            "Godlike Potion",
            "Potion of bound",
            "Oblivion Potion",
        ]

        if not isinstance(buff_config, dict):
            return buffs_to_use

        def _read_buff_state(raw_value):
            try:
                if isinstance(raw_value, (list, tuple)) and len(raw_value) >= 2:
                    return bool(raw_value[0]), max(1, int(raw_value[1]))
            except Exception:
                pass
            return False, 1

        for buff_name in priority_order:
            enabled, amount = _read_buff_state(buff_config.get(buff_name))
            if enabled:
                buffs_to_use.append((buff_name, amount))

        for buff_name, raw_value in buff_config.items():
            if buff_name in priority_order:
                continue
            enabled, amount = _read_buff_state(raw_value)
            if enabled:
                buffs_to_use.append((buff_name, amount))

        return buffs_to_use

    def auto_pop_buffs_for_current_biome(self, target_biome=None):
        if target_biome is None:
            target_biome = self.current_biome
        self.auto_pop_state = True
        try:
            self._action_scheduler.enqueue_action(
                lambda: self._auto_pop_buffs_for_current_biome_impl(target_biome=target_biome),
                name="auto_pop_current_biome",
                priority=0,
            )
        except Exception:
            try:
                self._auto_pop_buffs_for_current_biome_impl(target_biome=target_biome)
            except Exception:
                pass

    def _auto_pop_buffs_for_current_biome_impl(self, target_biome=None):
        self.auto_pop_state = True
        if target_biome is None:
            target_biome = self.current_biome
        try:
            if not target_biome or target_biome == "NORMAL": return
            if self.config.get("enable_idle_mode", False): return
            if getattr(self, "enable_potion_crafting_var", None) and self.enable_potion_crafting_var.get(): return

            biome_entry = self._get_auto_pop_biome_entry(target_biome)
            if not biome_entry.get("enabled", False): return

            buffs_to_use = self._build_auto_pop_buffs_to_use(biome_entry.get("buffs", {}))
            if not buffs_to_use: return

            inventory_click_delay = int(self.config.get("inventory_click_delay", "0")) / 1000.0
            warp_enabled = any(buff in ("Warp Potion", "Transcendent Potion") for buff, _ in buffs_to_use)

            if (
                self.is_fishing_mode_enabled()
                or bool(getattr(self, "on_auto_merchant_state", False))
                or bool(getattr(self, "_mt_running", False))
                or bool(getattr(self, "_br_sc_running", False))
                or bool((getattr(self, "_egg_collecting", False) or getattr(self, "_eden_running", False) or getattr(self, "_potion_thread_active", False)))
            ):
                self.append_log(f"[Auto Pop] Waiting for other actions to finish before popping buffs")
                wait_deadline = time.monotonic() + 50
                while time.monotonic() < wait_deadline:
                    if not self.detection_running or self.reconnecting_state: return
                    if self.current_biome != target_biome: return
                    still_busy = (
                        bool(getattr(self, "_fishing_busy", False))
                        or bool(getattr(self, "on_auto_merchant_state", False))
                        or bool(getattr(self, "_mt_running", False))
                        or bool(getattr(self, "_br_sc_running", False))
                        or bool((getattr(self, "_egg_collecting", False) or getattr(self, "_eden_running", False) or getattr(self, "_potion_thread_active", False)))
                    )
                    if not still_busy: break
                    time.sleep(0.55)
                time.sleep(0.5)

            for buff, amount in buffs_to_use:
                if not self.detection_running or self.reconnecting_state: return
                if self.current_biome != target_biome:
                    self.append_log(f"[Auto Pop] Biome changed to {self.current_biome}, stopping auto pop...")
                    self.send_webhook_status(
                        f"Biome changed to {self.current_biome}, stopping auto pop...",
                        color=0x34ebab,
                    )
                    return

                self.append_log(f"[Auto Pop] Preparing {buff} x{amount} in {target_biome}")

                additional_wait_time = 0
                if buff == "Oblivion Potion":
                    additional_wait_time = 0.85 * amount
                    if warp_enabled:
                        additional_wait_time *= 0.12

                for _ in range(5):
                    if not self.detection_running or self.reconnecting_state:
                        return
                    self.activate_roblox_window()
                    time.sleep(0.35)

                time.sleep(0.57)

                inventory_menu = self.config.get("inventory_menu", [36, 535])
                inventory_close_button = self.config.get("inventory_close_button", [1418, 298])
                items_tab = self.config.get("items_tab", [1272, 329])
                search_bar = self.config.get("search_bar", [855, 358])
                first_item_slot = self.config.get("first_item_inventory_slot_pos", [845, 460])
                amount_box = self.config.get("amount_box", [594, 570])
                use_button = self.config.get("use_button", [710, 573])

                self.Global_MouseClick(inventory_menu[0], inventory_menu[1])
                time.sleep(0.22 + inventory_click_delay)
                self.Global_MouseClick(items_tab[0], items_tab[1])
                time.sleep(0.22 + inventory_click_delay)
                self.Global_MouseClick(search_bar[0], search_bar[1], click=2)
                time.sleep(0.23 + inventory_click_delay)

                if not self.detection_running or self.reconnecting_state:
                    return
                if self.current_biome != target_biome:
                    self.append_log(f"[Auto Pop] Biome changed mid-inventory, closing and stopping")
                    self.Global_MouseClick(inventory_close_button[0], inventory_close_button[1])
                    time.sleep(0.15 + inventory_click_delay)
                    return

                self._safe_type_text(buff.lower())
                time.sleep(0.22 + inventory_click_delay)
                self.Global_MouseClick(first_item_slot[0], first_item_slot[1])
                time.sleep(0.22 + inventory_click_delay)

                try:
                    if not self._ocr_first_slot_matches(buff):
                        self.Global_MouseClick(inventory_close_button[0], inventory_close_button[1])
                        time.sleep(0.15 + inventory_click_delay)
                        continue
                except Exception:
                    pass

                self.Global_MouseClick(amount_box[0], amount_box[1])
                time.sleep(0.22 + inventory_click_delay)

                if not self.detection_running or self.reconnecting_state:
                    return

                pyautogui.hotkey('command', 'a') if sys.platform == 'darwin' else pyautogui.hotkey('ctrl', 'a')
                time.sleep(0.285 + inventory_click_delay)
                pyautogui.press('backspace')
                time.sleep(0.285 + inventory_click_delay)
                self._safe_type_text(str(amount))
                time.sleep(0.285 + inventory_click_delay)

                self.Global_MouseClick(use_button[0], use_button[1])
                time.sleep(0.3 + inventory_click_delay)

                self.append_log(f"[Auto Pop] Used {buff} x{amount} in {target_biome}")
                self.send_webhook_status(f"Used x{amount} {buff} in {target_biome}", color=0x34ebab)

                self.Global_MouseClick(inventory_close_button[0], inventory_close_button[1])
                time.sleep(0.32 + inventory_click_delay)

                if additional_wait_time > 0:
                    time.sleep(additional_wait_time)

        except Exception as e:
            self.error_logging(e, "Error in auto_pop_buffs_for_current_biome function")
        finally:
            self.auto_pop_state = False

    def auto_pop_buffs(self):
        self.auto_pop_buffs_for_current_biome()

    def auto_pop_buffs_individual(self):
        self.auto_pop_buffs_for_current_biome()