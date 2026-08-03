import os
import sys
import time
import json
import threading
import platform
import pyautogui

# Use pynput for reliable cross-platform input recording (works on macOS)
try:
    from pynput import mouse, keyboard
except ImportError:
    print("[Recorder] ERROR: pynput is not installed. Recording will not work.")
    print("Install it with: pip install pynput")
    # Provide dummy stubs so the class can still be instantiated
    class mouse:
        class Listener:
            def __init__(self, *args, **kwargs): pass
            def start(self): pass
            def stop(self): pass
        class Controller:
            def __init__(self): pass
    class keyboard:
        class Listener:
            def __init__(self, *args, **kwargs): pass
            def start(self): pass
            def stop(self): pass
        class Controller:
            def __init__(self): pass

# ── macOS crash workaround ───────────────────────────────────────────
# pynput on macOS (Apple Silicon especially) can crash the whole process
# with "trace trap" (SIGTRAP) — this happens inside native Quartz/pyobjc
# code when the NSSystemDefined event mask is active, and is triggered by
# things like Caps Lock / IME-switch key events. It's a native crash, not
# a Python exception, so it cannot be caught with try/except.
# Fix: https://github.com/moses-palmer/pynput/issues/510
# We don't need media/system-defined keys for this macro, so we strip
# that event mask from pynput's Darwin backend before any Listener runs.
if platform.system() == "Darwin":
    try:
        import Quartz
        from pynput.keyboard import _darwin as _pynput_darwin
        _pynput_darwin.Listener._EVENTS = (
            Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown)
            | Quartz.CGEventMaskBit(Quartz.kCGEventKeyUp)
            | Quartz.CGEventMaskBit(Quartz.kCGEventFlagsChanged)
        )
        print("[Recorder] Applied macOS pynput crash workaround (issue #510).")
    except Exception as e:
        print(f"[Recorder] Warning: could not apply macOS pynput workaround: {e}")

# Movement keys used by the obby macro
_MOVEMENT_KEYS = {"w", "a", "s", "d", "space"}


class RecorderMixin:
    # ── macOS permissions ────────────────────────────────────────────
    def _check_macos_permissions(self):
        """
        On macOS, both pynput (for capturing global mouse/keyboard events)
        and pyautogui (for synthesizing keyDown/keyUp during replay) need
        the process — Terminal, iTerm, VSCode, or the packaged .app —
        to be granted:
          - Accessibility          (System Settings > Privacy & Security > Accessibility)
          - Input Monitoring       (System Settings > Privacy & Security > Input Monitoring)
        Without these, pynput listeners silently receive no events instead
        of raising an error, which is why this is a print warning rather
        than a hard failure.
        """
        if sys.platform != "darwin":
            return
        print("[Recorder] macOS detected. If no events are captured, grant this app")
        print("           Accessibility + Input Monitoring permissions in")
        print("           System Settings > Privacy & Security, then restart it.")

    # ── Camera alignment ─────────────────────────────────────────────
    def align_camera(self):
        def _align():
            print("[Camera] Aligning camera...")
            collections_btn = self.config.get("collections_button", [0, 0])
            exit_collections_btn = self.config.get("exit_collections_button", [0, 0])

            if collections_btn[0] > 0:
                pyautogui.click(collections_btn[0], collections_btn[1])
                time.sleep(0.3)

            if exit_collections_btn[0] > 0:
                pyautogui.click(exit_collections_btn[0], exit_collections_btn[1])
                time.sleep(0.3)

            start_x = exit_collections_btn[0] if exit_collections_btn[0] > 0 else 500
            start_y = exit_collections_btn[1] if exit_collections_btn[1] > 0 else 500
            pyautogui.moveTo(start_x, start_y)
            pyautogui.mouseDown(button="right")
            time.sleep(0.1)
            pyautogui.moveTo(start_x, start_y + 75, duration=0.2)
            time.sleep(0.05)
            pyautogui.mouseUp(button="right")
            time.sleep(0.2)
            print("[Camera] Alignment finished.")

        threading.Thread(target=_align, daemon=True).start()

    # ── Recording ────────────────────────────────────────────────────
    def start_recording_path(self):
        if getattr(self, "_is_recording", False):
            return
        self._check_macos_permissions()
        print("[Recorder] Recording started...")
        self._is_recording = True
        self._recorded_events = []
        self._held_keys = set()  # suppress macOS key-repeat on_press spam
        self._record_start_time = time.perf_counter()

        # Start pynput listeners
        self._mouse_listener = mouse.Listener(on_move=self._on_mouse_move,
                                              on_click=self._on_mouse_click,
                                              on_scroll=self._on_mouse_scroll)
        self._keyboard_listener = keyboard.Listener(on_press=self._on_key_press,
                                                    on_release=self._on_key_release)
        self._mouse_listener.start()
        self._keyboard_listener.start()

    def _on_mouse_move(self, x, y):
        if not getattr(self, "_is_recording", False):
            return
        t = time.perf_counter() - self._record_start_time
        self._recorded_events.append({
            "type": "mouse_move",
            "x": x, "y": y,
            "button": "", "key": "", "delta": 0,
            "t": t
        })

    def _on_mouse_click(self, x, y, button, pressed):
        if not getattr(self, "_is_recording", False):
            return
        t = time.perf_counter() - self._record_start_time
        button_str = str(button).split('.')[-1]  # e.g., 'left', 'right'
        self._recorded_events.append({
            "type": "mouse_down" if pressed else "mouse_up",
            "x": x, "y": y,
            "button": button_str, "key": "", "delta": 0,
            "t": t
        })

    def _on_mouse_scroll(self, x, y, dx, dy):
        if not getattr(self, "_is_recording", False):
            return
        t = time.perf_counter() - self._record_start_time
        # dy: positive = scroll up, negative = scroll down
        self._recorded_events.append({
            "type": "mouse_wheel",
            "x": x, "y": y,
            "button": "", "key": "", "delta": dy,
            "t": t
        })

    @staticmethod
    def _normalize_key_name(key):
        try:
            key_name = key.char.lower()
        except AttributeError:
            key_name = str(key).replace('Key.', '').lower()
        return key_name

    def _on_key_press(self, key):
        if not getattr(self, "_is_recording", False):
            return
        key_name = self._normalize_key_name(key)
        # Skip function keys F1-F4 (commonly used for macro control)
        if key_name in ("f1", "f2", "f3", "f4"):
            return
        # macOS fires on_press repeatedly while a key is held down
        # (key-repeat). Only record the first press until the release.
        if key_name in self._held_keys:
            return
        self._held_keys.add(key_name)
        t = time.perf_counter() - self._record_start_time
        self._recorded_events.append({
            "type": "key_down",
            "x": 0, "y": 0, "button": "", "key": key_name, "delta": 0,
            "t": t
        })

    def _on_key_release(self, key):
        if not getattr(self, "_is_recording", False):
            return
        key_name = self._normalize_key_name(key)
        if key_name in ("f1", "f2", "f3", "f4"):
            return
        self._held_keys.discard(key_name)
        t = time.perf_counter() - self._record_start_time
        self._recorded_events.append({
            "type": "key_up",
            "x": 0, "y": 0, "button": "", "key": key_name, "delta": 0,
            "t": t
        })

    @staticmethod
    def _events_to_offset_duration(events):
        """
        Convert key_down/key_up events for movement keys into the
        [{"key", "start_offset", "duration"}, ...] format used by the
        obby macro player. Unmatched key_down events (e.g. a key still
        held when recording stopped) are dropped.
        """
        open_downs = {}
        out = []
        for ev in events:
            typ = ev.get("type")
            key = str(ev.get("key", "")).lower().strip()
            if key not in _MOVEMENT_KEYS:
                continue
            t = float(ev.get("t", 0.0))
            if typ == "key_down":
                open_downs.setdefault(key, []).append(t)
            elif typ == "key_up":
                stack = open_downs.get(key)
                if stack:
                    start = stack.pop(0)
                    duration = max(0.0, t - start)
                    out.append({"key": key, "start_offset": round(start, 4), "duration": round(duration, 4)})
        out.sort(key=lambda e: e["start_offset"])
        return out

    def stop_recording_path(self, filename, save_dir="recorded_files"):
        if not getattr(self, "_is_recording", False):
            return "Not recording."

        self._is_recording = False
        # Stop listeners
        try:
            self._mouse_listener.stop()
        except Exception:
            pass
        try:
            self._keyboard_listener.stop()
        except Exception:
            pass

        # Trim trailing left-click noise
        if self._recorded_events:
            cutoff_t = self._recorded_events[-1]["t"] - 0.5
            while self._recorded_events and self._recorded_events[-1]["t"] > cutoff_t:
                last = self._recorded_events[-1]
                if last["type"] in ("mouse_down", "mouse_up", "mouse_move") and last.get("button", "left") == "left":
                    self._recorded_events.pop()
                else:
                    break

        os.makedirs(save_dir, exist_ok=True)

        # Full raw log (mouse + keyboard) — used by replay_path_recording below.
        filepath = os.path.join(save_dir, f"{filename}.json")
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump({"events": self._recorded_events}, f, indent=4)
        except Exception as e:
            return str(e)

        # Movement-only log in start_offset/duration format — used by the obby macro.
        obby_events = self._events_to_offset_duration(self._recorded_events)
        obby_filepath = os.path.join(save_dir, f"{filename}_obby.json")
        try:
            with open(obby_filepath, "w", encoding="utf-8") as f:
                json.dump(obby_events, f, indent=4)
        except Exception as e:
            print(f"[Recorder] Warning: failed to save obby-format file: {e}")

        print(f"[Recorder] Stopped recording. Saved {filepath}")
        print(f"[Recorder]   and {obby_filepath} ({len(obby_events)} movement events)")
        return "OK"

    # ── Replay ───────────────────────────────────────────────────────
    def replay_path_recording(self, filename, save_dir="recorded_files"):
        filepath = os.path.join(save_dir, f"{filename}.json")
        if not os.path.exists(filepath):
            return f"Error: File not found: {filepath}"

        print(f"[Recorder] Loading macro from {filepath}")
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            events = data.get("events", [])
        except Exception as e:
            return f"Error: Failed to load file: {e}"

        self._cancel_replay = False

        # Use pynput to listen for ESC key to cancel replay
        def _on_esc_press(key):
            try:
                if key == keyboard.Key.esc:
                    print("[Recorder] Replay cancelled by user (ESC).")
                    self._cancel_replay = True
                    return False  # stop listener
            except Exception:
                pass
            return True

        esc_listener = keyboard.Listener(on_press=_on_esc_press)
        esc_listener.start()

        start_time = time.perf_counter()
        pressed_keys = set()

        # If event timestamps were stored in milliseconds, normalize them to seconds.
        time_scale = 1.0
        max_t = 0.0
        for event in events:
            try:
                raw_t = float(event.get("t", 0.0))
            except Exception:
                raw_t = 0.0
            if raw_t > max_t:
                max_t = raw_t
        if max_t > 1000.0:
            time_scale = 0.001

        for event in events:
            if self._cancel_replay:
                break
            target_time = start_time + float(event.get("t", 0.0)) * time_scale
            now = time.perf_counter()
            if target_time > now:
                if target_time - now > 0.02:
                    time.sleep((target_time - now) - 0.015)
                while time.perf_counter() < target_time:
                    if self._cancel_replay:
                        break

            if self._cancel_replay:
                break

            typ = event.get("type", "")
            try:
                if typ == "mouse_move":
                    pyautogui.moveTo(int(event.get("x", 0)), int(event.get("y", 0)), duration=0)
                elif typ == "mouse_down":
                    pyautogui.mouseDown(button=event.get("button", "left"))
                elif typ == "mouse_up":
                    pyautogui.mouseUp(button=event.get("button", "left"))
                elif typ == "mouse_wheel":
                    delta = event.get("delta", 0)
                    if delta != 0:
                        pyautogui.scroll(int(delta))  # positive = scroll up
                elif typ in ("key_down", "key_up"):
                    k = event.get("key", "")
                    if k and k not in ("f1", "f2", "f3", "f4", "esc"):
                        try:
                            if typ == "key_down":
                                pyautogui.keyDown(k)
                                pressed_keys.add(k)
                            else:
                                pyautogui.keyUp(k)
                                pressed_keys.discard(k)
                        except Exception:
                            pass
            except Exception:
                pass

        # Release any stuck keys
        if pressed_keys:
            print(f"[Recorder] Releasing {len(pressed_keys)} stuck keys...")
            for k in list(pressed_keys):
                try:
                    pyautogui.keyUp(k)
                except Exception:
                    pass

        # Stop the ESC listener
        try:
            esc_listener.stop()
        except Exception:
            pass

        print("[Recorder] Macro finished.")
        return "Cancelled" if self._cancel_replay else "Finished"