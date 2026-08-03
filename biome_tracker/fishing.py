import json
import threading
import time
from pathlib import Path
from typing import Any, Callable
try:
    import keyboard
except Exception:
    keyboard = None
import cv2
import numpy as np
import pyautogui

try:
    import pyperclip
except ImportError:
    pyperclip = None

try:
    import mss
except Exception:
    mss = None

pyautogui.FAILSAFE = False

DEFAULT_FISHING_CONFIG = {
    "fishing_bar_region": [757, 762, 405, 21],
    "fishing_detect_pixel": [1176, 836],
    "fishing_click_position": [862, 843],
    "fishing_midbar_sample_pos": [955, 767],
    "fishing_close_button_pos": [1113, 342],
    "fishing_flarg_dialogue_box": [1046, 782],
    "fishing_shop_open_button": [616, 938],
    "fishing_shop_sell_tab": [1285, 312],
    "fishing_shop_close_button": [1458, 269],
    "fishing_shop_first_fish": [827, 404],
    "fishing_shop_sell_all_button": [662, 799],
    "fishing_confirm_sell_all_button": [800, 619],
    "collections_button": [33, 443],
    "exit_collections_button": [385, 164],
    "aura_menu": [1200, 500],
    "aura_search_bar": [834, 364],
    "first_aura_slot_pos": [0, 0],
    "equip_aura_button": [0, 0],
    "inventory_close_button": [1418, 298],
}

WALK_TO_FISH_EVENTS: list[dict[str, Any]] = [
    {
        "key": "a",
        "start_offset": 0.3305,
        "duration": 1.9386
    },
    {
        "key": "w",
        "start_offset": 0.3468,
        "duration": 7.9149
    }
]
WALK_TO_SELL_FISH_EVENTS: list[dict[str, Any]] = [
    {
        "key": "a",
        "start_offset": 0.1697,
        "duration": 4.1316
    },
    {
        "key": "w",
        "start_offset": 0.1813,
        "duration": 7.1363
    },
    {
        "key": "a",
        "start_offset": 5.9459,
        "duration": 1.3551
    },
    {
        "key": "d",
        "start_offset": 7.5474,
        "duration": 0.3011
    },
    {
        "key": "a",
        "start_offset": 7.982,
        "duration": 1.5226
    },
    {
        "key": "space",
        "start_offset": 8.0648,
        "duration": 0.1198
    },
    {
        "key": "space",
        "start_offset": 8.6885,
        "duration": 0.1581
    },
    {
        "key": "w",
        "start_offset": 9.5051,
        "duration": 1.119
    },
    {
        "key": "d",
        "start_offset": 10.622,
        "duration": 1.1155
    },
    {
        "key": "space",
        "start_offset": 10.7531,
        "duration": 0.1432
    },
    {
        "key": "w",
        "start_offset": 11.7985,
        "duration": 0.3238
    }
]
def _load_config_file() -> dict[str, Any]:
    try:
        from .config import get_config_file
        config_path = get_config_file()
    except Exception:
        config_path = Path(__file__).resolve().with_name("config.json")

    if not config_path.exists():
        return {}
    try:
        content = json.loads(config_path.read_text(encoding="utf-8"))
        return content if isinstance(content, dict) else {}
    except Exception:
        return {}


def _normalize_event_entry(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None

    key = str(raw.get("key", "")).strip().lower()
    if not key:
        return None

    try:
        start_offset = float(raw.get("start_offset", raw.get("t", 0.0)))
    except Exception:
        start_offset = 0.0

    try:
        duration = float(raw.get("duration", 0.0))
    except Exception:
        duration = 0.0

    entry: dict[str, Any] = {"key": key, "start_offset": start_offset, "duration": duration}
    if "type" in raw:
        entry["type"] = str(raw.get("type", ""))
    return entry


def _load_event_entries(raw_value: Any, fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(raw_value, (list, tuple)):
        events: list[dict[str, Any]] = []
        for item in raw_value:
            entry = _normalize_event_entry(item)
            if entry is not None:
                events.append(entry)
        return events if events else list(fallback)

    if isinstance(raw_value, str) and raw_value.strip():
        path = Path(raw_value).expanduser()
        if path.exists():
            try:
                content = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                content = None
            if isinstance(content, (list, tuple)):
                events = []
                for item in content:
                    entry = _normalize_event_entry(item)
                    if entry is not None:
                        events.append(entry)
                return events if events else list(fallback)

    return list(fallback)


def _coerce_point(raw: Any, fallback: list[int]) -> tuple[int, int]:
    if not isinstance(raw, (list, tuple)) or len(raw) < 2:
        return fallback[0], fallback[1]
    try:
        return int(raw[0]), int(raw[1])
    except Exception:
        return fallback[0], fallback[1]


def _coerce_region(raw: Any, fallback: list[int]) -> tuple[int, int, int, int]:
    if not isinstance(raw, (list, tuple)) or len(raw) < 4:
        return fallback[0], fallback[1], fallback[2], fallback[3]
    try:
        x = int(raw[0])
        y = int(raw[1])
        w = max(1, int(raw[2]))
        h = max(1, int(raw[3]))
        return x, y, w, h
    except Exception:
        return fallback[0], fallback[1], fallback[2], fallback[3]


def _coerce_int(raw: Any, fallback: int, min_value: int, max_value: int) -> int:
    try:
        value = int(raw)
        if value < min_value:
            return min_value
        if value > max_value:
            return max_value
        return value
    except Exception:
        return fallback


def _coerce_float(raw: Any, fallback: float, min_value: float, max_value: float) -> float:
    try:
        value = float(raw)
        if value < min_value:
            return min_value
        if value > max_value:
            return max_value
        return value
    except Exception:
        return fallback


def load_fishing_config(raw_config: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = raw_config if isinstance(raw_config, dict) else _load_config_file()
    start_fishing_button = raw.get("start_fishing_button", raw.get("fishing_click_position"))
    auto_reconnect_enabled = bool(raw.get("auto_reconnect", False))
    fishing_failsafe_enabled = bool(raw.get("fishing_failsafe_rejoin", False)) and auto_reconnect_enabled
    movement_aura_name = str(raw.get("fishing_movement_aura_name", "")).strip()
    walk_to_fish_events = _load_event_entries(
        raw.get("fishing_walk_to_fish_events", raw.get("fishing_walk_to_fish_events_path")),
        WALK_TO_FISH_EVENTS,
    )
    walk_to_sell_fish_events = _load_event_entries(
        raw.get("fishing_walk_to_sell_fish_events", raw.get("fishing_walk_to_sell_fish_events_path")),
        WALK_TO_SELL_FISH_EVENTS,
    )
    return {
        "fishing_bar_region": _coerce_region(raw.get("fishing_bar_region"), DEFAULT_FISHING_CONFIG["fishing_bar_region"]),
        "fishing_detect_pixel": _coerce_point(raw.get("fishing_detect_pixel"), DEFAULT_FISHING_CONFIG["fishing_detect_pixel"]),
        "fishing_click_position": _coerce_point(start_fishing_button, DEFAULT_FISHING_CONFIG["fishing_click_position"]),
        "fishing_midbar_sample_pos": _coerce_point(raw.get("fishing_midbar_sample_pos"), DEFAULT_FISHING_CONFIG["fishing_midbar_sample_pos"]),
        "fishing_close_button_pos": _coerce_point(raw.get("fishing_close_button_pos"), DEFAULT_FISHING_CONFIG["fishing_close_button_pos"]),
        "fishing_flarg_dialogue_box": _coerce_point(raw.get("fishing_flarg_dialogue_box"), DEFAULT_FISHING_CONFIG["fishing_flarg_dialogue_box"]),
        "fishing_shop_open_button": _coerce_point(raw.get("fishing_shop_open_button"), DEFAULT_FISHING_CONFIG["fishing_shop_open_button"]),
        "fishing_shop_sell_tab": _coerce_point(raw.get("fishing_shop_sell_tab"), DEFAULT_FISHING_CONFIG["fishing_shop_sell_tab"]),
        "fishing_shop_close_button": _coerce_point(raw.get("fishing_shop_close_button"), DEFAULT_FISHING_CONFIG["fishing_shop_close_button"]),
        "fishing_shop_first_fish": _coerce_point(raw.get("fishing_shop_first_fish"), DEFAULT_FISHING_CONFIG["fishing_shop_first_fish"]),
        "fishing_shop_sell_all_button": _coerce_point(raw.get("fishing_shop_sell_all_button"), DEFAULT_FISHING_CONFIG["fishing_shop_sell_all_button"]),
        "fishing_confirm_sell_all_button": _coerce_point(raw.get("fishing_confirm_sell_all_button"), DEFAULT_FISHING_CONFIG["fishing_confirm_sell_all_button"]),
        "collections_button": _coerce_point(raw.get("collections_button"), DEFAULT_FISHING_CONFIG["collections_button"]),
        "exit_collections_button": _coerce_point(raw.get("exit_collections_button"), DEFAULT_FISHING_CONFIG["exit_collections_button"]),
        "aura_menu": _coerce_point(raw.get("aura_menu"), DEFAULT_FISHING_CONFIG["aura_menu"]),
        "aura_search_bar": _coerce_point(raw.get("aura_search_bar"), DEFAULT_FISHING_CONFIG["aura_search_bar"]),
        "first_aura_slot_pos": _coerce_point(raw.get("first_aura_slot_pos"), DEFAULT_FISHING_CONFIG["first_aura_slot_pos"]),
        "equip_aura_button": _coerce_point(raw.get("equip_aura_button"), DEFAULT_FISHING_CONFIG["equip_aura_button"]),
        "inventory_close_button": _coerce_point(raw.get("inventory_close_button"), DEFAULT_FISHING_CONFIG["inventory_close_button"]),
        "fishing_failsafe_rejoin": fishing_failsafe_enabled,
        "fishing_enable_selling": bool(raw.get("fishing_enable_selling", False)),
        "fishing_sell_after_x_fish": _coerce_int(raw.get("fishing_sell_after_x_fish"), 30, 1, 100000),
        "fishing_sell_how_many_fish": _coerce_int(raw.get("fishing_sell_how_many_fish"), 1, 1, 100000),
        "fishing_equip_aura_before_movement": bool(raw.get("fishing_equip_aura_before_movement", False)),
        "fishing_movement_aura_name": movement_aura_name,
        "fishing_movement_aura_delay_seconds": _coerce_float(raw.get("fishing_movement_aura_delay_seconds"), 0.67, 0.1, 2.0),
        "merchant_teleporter": bool(raw.get("merchant_teleporter", False)),
        "fishing_use_merchant_every_x_fish": bool(raw.get("fishing_use_merchant_every_x_fish", False)),
        "fishing_merchant_every_x_fish": _coerce_int(raw.get("fishing_merchant_every_x_fish"), 30, 1, 100000),
        "fishing_use_merchant_ocr_every_x_fish": bool(raw.get("fishing_use_merchant_ocr_every_x_fish", False)),
        "fishing_merchant_ocr_every_x_fish_amt": _coerce_int(raw.get("fishing_merchant_ocr_every_x_fish_amt"), 30, 1, 100000),
        "fishing_use_br_sc_every_x_fish": bool(raw.get("fishing_use_br_sc_every_x_fish", False)),
        "fishing_br_sc_every_x_fish": _coerce_int(raw.get("fishing_br_sc_every_x_fish"), 30, 1, 100000),
        "fishing_actions_delay_ms": _coerce_int(raw.get("fishing_actions_delay_ms"), 100, 0, 5000),
        "fishing_playback_multiplier": _coerce_float(raw.get("fishing_playback_multiplier"), 1.0, 1.0, 2.0),
        "non_vip_movement_path": bool(raw.get("non_vip_movement_path", False)),
        "egg_ocr_detect_special": bool(raw.get("egg_ocr_detect_special", False)),
        # Performance tuning knobs (optional in config.json)
        "fishing_click_burst": _coerce_int(raw.get("fishing_click_burst"), 2, 1, 8),
        "fishing_reel_loop_sleep": _coerce_float(raw.get("fishing_reel_loop_sleep"), 0.004, 0.001, 0.03),
        "fishing_idle_poll_sleep": _coerce_float(raw.get("fishing_idle_poll_sleep"), 0.004, 0.001, 0.05),
        "fishing_pre_reel_wait": _coerce_float(raw.get("fishing_pre_reel_wait"), 0.18, 0.05, 0.5),
        "fishing_bar_color_tolerance": _coerce_int(raw.get("fishing_bar_color_tolerance"), 12, 3, 40),
        "fishing_bar_scan_height": _coerce_int(raw.get("fishing_bar_scan_height"), 3, 1, 30),
        "fishing_walk_to_fish_events": walk_to_fish_events,
        "fishing_walk_to_sell_fish_events": walk_to_sell_fish_events,
    }


def _get_fishing_actions_delay_seconds(cfg: dict[str, Any]) -> float:
    return _coerce_int(cfg.get("fishing_actions_delay_ms"), 100, 0, 5000) / 1000.0


def _get_pixel_rgb(x: int, y: int, sct: Any | None = None) -> tuple[int, int, int]:
    if sct is not None:
        try:
            shot = sct.grab({"left": int(x), "top": int(y), "width": 1, "height": 1})
            arr = np.frombuffer(shot.bgra, dtype=np.uint8).reshape((1, 1, 4))
            b, g, r = arr[0, 0, 0], arr[0, 0, 1], arr[0, 0, 2]
            return int(r), int(g), int(b)
        except Exception:
            pass
    pixel = pyautogui.screenshot(region=(x, y, 1, 1)).getpixel((0, 0))
    return int(pixel[0]), int(pixel[1]), int(pixel[2])


def _pick_scan_region(bar_region: tuple[int, int, int, int], scan_height: int) -> tuple[int, int, int, int]:
    x, y, w, h = bar_region
    sh = max(1, min(int(scan_height), max(1, int(h))))
    scan_y = y + max(0, (h - sh) // 2)
    return int(x), int(scan_y), int(w), int(sh)


def _grab_region_bgr(region: tuple[int, int, int, int], sct: Any | None = None) -> np.ndarray:
    x, y, w, h = region
    if sct is not None:
        try:
            shot = sct.grab({"left": int(x), "top": int(y), "width": int(w), "height": int(h)})
            arr = np.frombuffer(shot.bgra, dtype=np.uint8).reshape((int(h), int(w), 4))
            return arr[:, :, :3]
        except Exception:
            pass

    pil_img = pyautogui.screenshot(region=(int(x), int(y), int(w), int(h)))
    arr = np.array(pil_img)
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def detect_colour(
    bar_color: tuple[int, int, int],
    bar_region: tuple[int, int, int, int],
    *,
    tolerance: int = 12,
    scan_height: int = 3,
    sct: Any | None = None,
) -> bool:
    scan_region = _pick_scan_region(bar_region, scan_height=scan_height)
    bgr = _grab_region_bgr(scan_region, sct=sct)
    lower_bound = np.array([
        max(0, bar_color[2] - tolerance),
        max(0, bar_color[1] - tolerance),
        max(0, bar_color[0] - tolerance)
    ])
    upper_bound = np.array([
        min(255, bar_color[2] + tolerance),
        min(255, bar_color[1] + tolerance),
        min(255, bar_color[0] + tolerance)
    ])
    mask = cv2.inRange(bgr, lower_bound, upper_bound)
    return bool(np.any(mask))


def is_indicator_active(pixel: tuple[int, ...], white_threshold: int = 250) -> bool:
    return len(pixel) >= 3 and pixel[0] >= white_threshold and pixel[1] >= white_threshold and pixel[2] >= white_threshold


# macOS‑friendly key handling using pyautogui
def _pyautogui_click(x: int, y: int, clicks: int = 1, button: str = "left", speed: int = 3) -> None:
    for _ in range(clicks):
        pyautogui.click(x, y, button=button)
        if clicks > 1:
            time.sleep(0.02)

def _pyautogui_key_tap(key: str) -> None:
    pyautogui.press(key)

def _pyautogui_key_down(key: str) -> None:
    pyautogui.keyDown(key)

def _pyautogui_key_up(key: str) -> None:
    pyautogui.keyUp(key)

def _safe_type_text(text: str, cfg: dict[str, Any] | None = None) -> None:
    """Type text using pyautogui.write, with optional clipboard for azerty mode."""
    text = str(text)
    if cfg and cfg.get("azerty_mode", False) and pyperclip is not None:
        try:
            pyperclip.copy(text)
            pyautogui.hotkey('command', 'v')  # macOS uses Command+V
            return
        except Exception:
            pass
    pyautogui.write(text, interval=0.01)


# NON-VIP MULTIPLIER
NON_VIP_WALK_SPEED_MULTIPLIER = 1.22
_MOVEMENT_KEYS = frozenset({"w", "a", "s", "d"})

def _run_recorded_events(
    *,
    events: list[dict[str, Any]],
    sleep_interruptible: Callable[[float, float], bool],
    should_continue: Callable[[], bool],
    can_run: Callable[[], bool],
    speed_multiplier: float = 1.0,
) -> bool:
    import select, time  # added for precise sleeps
    pressed_keys: set[str] = set()
    last_t = 0.0
    try:
        for ev in events:
            if not should_continue() or not can_run():
                return False

            if "start_offset" in ev or "duration" in ev:
                t = float(ev.get("start_offset", ev.get("t", last_t)))
                dt = t - last_t
                duration = float(ev.get("duration", 0.0))

                if speed_multiplier > 1.0 and duration > 0:
                    ev_key = str(ev.get("key", "")).lower().strip()
                    if ev_key in _MOVEMENT_KEYS:
                        duration = duration / speed_multiplier

                if dt > 0:
                    end_time = time.perf_counter() + dt
                    while True:
                        remaining = end_time - time.perf_counter()
                        if remaining <= 0:
                            break
                        if not should_continue() or not can_run():
                            return False
                        if remaining < 0.002:
                            while time.perf_counter() < end_time:
                                pass
                            break
                        sleep_chunk = min(remaining - 0.002, 0.010)
                        select.select([], [], [], sleep_chunk)

                k = str(ev.get("key", "")).lower().strip()
                if k:
                    _pyautogui_key_down(k)
                    pressed_keys.add(k)
                    if duration > 0:
                        end_time = time.perf_counter() + duration
                        while True:
                            remaining = end_time - time.perf_counter()
                            if remaining <= 0:
                                break
                            if not should_continue() or not can_run():
                                return False
                            if remaining < 0.002:
                                while time.perf_counter() < end_time:
                                    pass
                                break
                            sleep_chunk = min(remaining - 0.002, 0.010)
                            select.select([], [], [], sleep_chunk)
                        _pyautogui_key_up(k)
                        pressed_keys.discard(k)

                last_t = t
                continue

            t = float(ev.get("t", last_t))
            dt = t - last_t

            if speed_multiplier > 1.0 and dt > 0:
                ev_key = str(ev.get("key", "")).lower().strip()
                ev_type = str(ev.get("type", ""))
                if ev_type in ("key_down", "key_up") and ev_key in _MOVEMENT_KEYS:
                    dt = dt / speed_multiplier

            if dt > 0:
                end_time = time.perf_counter() + dt
                while True:
                    remaining = end_time - time.perf_counter()
                    if remaining <= 0:
                        break
                    if not should_continue() or not can_run():
                        return False
                    if remaining < 0.002:
                        while time.perf_counter() < end_time:
                            pass
                        break
                    sleep_chunk = min(remaining - 0.002, 0.010)
                    select.select([], [], [], sleep_chunk)

            typ = str(ev.get("type", ""))
            try:
                if typ == "mouse_move":
                    pyautogui.moveTo(int(ev.get("x", 0)), int(ev.get("y", 0)), duration=0)
                elif typ == "mouse_down":
                    pyautogui.mouseDown(button=str(ev.get("button", "left")))
                elif typ == "mouse_up":
                    pyautogui.mouseUp(button=str(ev.get("button", "left")))
                elif typ == "mouse_wheel":
                    delta = int(ev.get("delta", 0))
                    if delta != 0:
                        pyautogui.scroll(delta)
                elif typ == "key_down":
                    k = str(ev.get("key", "")).lower().strip()
                    if k:
                        _pyautogui_key_down(k)
                        pressed_keys.add(k)
                elif typ == "key_up":
                    k = str(ev.get("key", "")).lower().strip()
                    if k:
                        _pyautogui_key_up(k)
                        pressed_keys.discard(k)
            except Exception:
                pass

            last_t = t
        return should_continue() and can_run()
    finally:
        for key_name in list(pressed_keys):
            try:
                _pyautogui_key_up(key_name)
            except Exception:
                pass

        for k in ("w", "a", "s", "d", "space"):
            try:
                _pyautogui_key_up(k)
            except Exception:
                pass
            select.select([], [], [], 0.02)

def _run_pre_fishing_sequence(
    *,
    cfg: dict[str, Any],
    sleep_interruptible: Callable[[float, float], bool],
    should_continue: Callable[[], bool],
    can_run: Callable[[], bool],
    activate_roblox_cb: Callable[[], None] | None = None,
    close_chat_fn: Callable[[], None] | None = None,
    egg_ocr_check_cb: Callable[[], None] | None = None,
) -> bool:
    if not should_continue() or not can_run():
        return False

    if egg_ocr_check_cb is not None and bool(cfg.get("egg_ocr_detect_special", False)):
        try:
            egg_ocr_check_cb()
            print("egg ocr check in fishing done")
        except Exception as e:
            print(f"[Fishing] egg_ocr_check_cb error: {e}")

    fishing_actions_delay = _get_fishing_actions_delay_seconds(cfg)
    if not _run_respawn_sequence(
        sleep_interruptible=sleep_interruptible,
        should_continue=should_continue,
        can_run=can_run,
        action_delay_seconds=fishing_actions_delay,
        activate_roblox_cb=activate_roblox_cb,
    ):
        return False

    # Close chat if open before clicking collection button
    if close_chat_fn is not None:
        try:
            print("[Fishing] Checking and closing chat if open...")
            close_chat_fn()
        except Exception as e:
            print(f"[Fishing] close_chat_fn error: {e}")
    if not sleep_interruptible(0.2 + fishing_actions_delay):
        return False

    collections_x, collections_y = cfg["collections_button"]
    if collections_x > 0:
        _pyautogui_click(collections_x, collections_y)
    if not sleep_interruptible(1.0 + fishing_actions_delay):
        return False

    exit_x, exit_y = cfg["exit_collections_button"]
    if exit_x > 0:
        _pyautogui_click(exit_x, exit_y)
    if not sleep_interruptible(0.2 + fishing_actions_delay):
        return False

    return sleep_interruptible(0.5 + fishing_actions_delay)


def _run_respawn_sequence(
    *,
    sleep_interruptible: Callable[[float, float], bool],
    should_continue: Callable[[], bool],
    can_run: Callable[[], bool],
    action_delay_seconds: float = 0.0,
    activate_roblox_cb: Callable[[], None] | None = None,
) -> bool:
    if not should_continue() or not can_run():
        return False

    if activate_roblox_cb is not None:
        for _ in range(4):
            try:
                activate_roblox_cb()
            except Exception:
                pass
            if not sleep_interruptible(0.5 + action_delay_seconds):
                return False

    _pyautogui_key_tap("esc")
    if not sleep_interruptible(1.25 + action_delay_seconds):
        return False

    _pyautogui_key_tap("r")
    if not sleep_interruptible(0.75 + action_delay_seconds):
        return False

    _pyautogui_key_tap("enter")
    if not sleep_interruptible(5.5 + action_delay_seconds):
        return False

    return True


def _run_walk_to_fish_path(
    *,
    cfg: dict[str, Any] | None = None,
    sleep_interruptible: Callable[[float, float], bool],
    should_continue: Callable[[], bool],
    can_run: Callable[[], bool],
    speed_multiplier: float = 1.0,
) -> bool:
    events = []
    if cfg is not None:
        events = list(cfg.get("fishing_walk_to_fish_events", []))
    if not events:
        events = list(WALK_TO_FISH_EVENTS)
    if not events:
        return False
    return _run_recorded_events(
        events=events,
        sleep_interruptible=sleep_interruptible,
        should_continue=should_continue,
        can_run=can_run,
        speed_multiplier=speed_multiplier,
    )


def _run_walk_to_sell_fish_path(
    *,
    cfg: dict[str, Any] | None = None,
    sleep_interruptible: Callable[[float, float], bool],
    should_continue: Callable[[], bool],
    can_run: Callable[[], bool],
    speed_multiplier: float = 1.0,
) -> bool:
    events = []
    if cfg is not None:
        events = list(cfg.get("fishing_walk_to_sell_fish_events", []))
    if not events:
        events = list(WALK_TO_SELL_FISH_EVENTS)
    if not events:
        return True
    return _run_recorded_events(
        events=events,
        sleep_interruptible=sleep_interruptible,
        should_continue=should_continue,
        can_run=can_run,
        speed_multiplier=speed_multiplier,
    )


def _run_equip_aura_before_movement(
    *,
    cfg: dict[str, Any],
    sleep_interruptible: Callable[[float, float], bool],
    should_continue: Callable[[], bool],
    can_run: Callable[[], bool],
) -> bool:
    if not bool(cfg.get("fishing_equip_aura_before_movement", False)):
        return True

    aura_name = str(cfg.get("fishing_movement_aura_name", "")).strip()
    if not aura_name:
        return True

    if not should_continue() or not can_run():
        return False

    step_delay = float(cfg.get("fishing_movement_aura_delay_seconds", 0.67)) + _get_fishing_actions_delay_seconds(cfg)
    aura_menu_x, aura_menu_y = cfg["aura_menu"]
    aura_search_x, aura_search_y = cfg["aura_search_bar"]
    first_slot_x, first_slot_y = cfg["first_aura_slot_pos"]
    equip_x, equip_y = cfg["equip_aura_button"]
    close_x, close_y = cfg["inventory_close_button"]

    if aura_menu_x > 0:
        _pyautogui_click(aura_menu_x, aura_menu_y)
    if not sleep_interruptible(step_delay):
        return False

    if aura_search_x > 0:
        _pyautogui_click(aura_search_x, aura_search_y)
    if not sleep_interruptible(step_delay):
        return False

    try:
        _safe_type_text(aura_name, cfg)
    except Exception:
        pass
    if not sleep_interruptible(step_delay):
        return False

    _pyautogui_key_tap("enter")
    if not sleep_interruptible(step_delay):
        return False

    if first_slot_x > 0:
        pyautogui.moveTo(first_slot_x, first_slot_y)
        if not sleep_interruptible(step_delay): return False
        try:
            pyautogui.scroll(5000)  # scroll up
        except Exception:
            pass
        if not sleep_interruptible(step_delay): return False
        _pyautogui_click(first_slot_x, first_slot_y)


    if not sleep_interruptible(step_delay): return False

    if equip_x > 0:
        _pyautogui_click(equip_x, equip_y)
    if not sleep_interruptible(step_delay):
        return False

    if close_x > 0:
        _pyautogui_click(close_x, close_y)
        if not sleep_interruptible(step_delay):
            return False

    return True


def _run_sell_fish_sequence(
    *,
    cfg: dict[str, Any],
    fish_sell_count: int,
    sleep_interruptible: Callable[[float, float], bool],
    should_continue: Callable[[], bool],
    can_run: Callable[[], bool],
    activate_roblox_cb: Callable[[], None] | None = None,
    close_chat_fn: Callable[[], None] | None = None,
    set_busy_cb: Callable[[bool], None] | None = None,
    egg_ocr_check_cb: Callable[[], None] | None = None,
) -> bool:
    if fish_sell_count <= 0:
        return True
    if set_busy_cb is not None:
        try:
            set_busy_cb(True)
        except Exception:
            pass

    if egg_ocr_check_cb is not None and bool(cfg.get("egg_ocr_detect_special", False)):
        try:
            egg_ocr_check_cb()
        except Exception as e:
            print(f"[Fishing] egg_ocr_check_cb error in sell sequence: {e}")

    fishing_actions_delay = _get_fishing_actions_delay_seconds(cfg)
    if not _run_respawn_sequence(
        sleep_interruptible=sleep_interruptible,
        should_continue=should_continue,
        can_run=can_run,
        action_delay_seconds=fishing_actions_delay,
        activate_roblox_cb=activate_roblox_cb,
    ):
        return False

    if close_chat_fn is not None:
        try:
            close_chat_fn()
        except Exception as e:
            print(f"[Fishing] close_chat_fn error before selling: {e}")
    if not sleep_interruptible(0.2 + fishing_actions_delay):
        return False

    collections_x, collections_y = cfg["collections_button"]
    if collections_x > 0:
        _pyautogui_click(collections_x, collections_y)
    if not sleep_interruptible(1.0 + fishing_actions_delay):
        return False

    exit_x, exit_y = cfg["exit_collections_button"]
    if exit_x > 0:
        _pyautogui_click(exit_x, exit_y)
    if not sleep_interruptible(0.2 + fishing_actions_delay):
        return False

    if not _run_equip_aura_before_movement(
        cfg=cfg,
        sleep_interruptible=sleep_interruptible,
        should_continue=should_continue,
        can_run=can_run,
    ):
        return False

    non_vip = bool(cfg.get("non_vip_movement_path", False))
    _walk_mult = NON_VIP_WALK_SPEED_MULTIPLIER if non_vip else 1.0
    _playback_mult = float(cfg.get("fishing_playback_multiplier", 1.0))
    _combined_multiplier = _walk_mult * _playback_mult
    if not _run_walk_to_sell_fish_path(
        cfg=cfg,
        sleep_interruptible=sleep_interruptible,
        should_continue=should_continue,
        can_run=can_run,
        speed_multiplier=_combined_multiplier,
    ):
        return False

    dialogue_x, dialogue_y = cfg["fishing_flarg_dialogue_box"]
    if dialogue_x > 0:
        _pyautogui_click(dialogue_x, dialogue_y)
        if not sleep_interruptible(0.3 + fishing_actions_delay):
            return False

        if not sleep_interruptible(0.2 + fishing_actions_delay):
            return False
        _pyautogui_click(dialogue_x, dialogue_y)
    if not sleep_interruptible(0.6 + fishing_actions_delay):
        return False

    shop_x, shop_y = cfg["fishing_shop_open_button"]
    if shop_x > 0:
        _pyautogui_click(shop_x, shop_y)
    if not sleep_interruptible(1.5 + fishing_actions_delay):
        return False

    sell_tab_x, sell_tab_y = cfg["fishing_shop_sell_tab"]
    close_shop_x, close_shop_y = cfg["fishing_shop_close_button"]
    first_fish_x, first_fish_y = cfg["fishing_shop_first_fish"]
    sell_x, sell_y = cfg["fishing_shop_sell_all_button"]
    confirm_x, confirm_y = cfg["fishing_confirm_sell_all_button"]
    for _ in range(max(1, int(fish_sell_count))):
        if not should_continue() or not can_run():
            return False
        if sell_tab_x > 0:
            _pyautogui_click(sell_tab_x, sell_tab_y)
        if not sleep_interruptible(0.3 + fishing_actions_delay):
            return False
        if first_fish_x > 0:
            _pyautogui_click(first_fish_x, first_fish_y)
        if not sleep_interruptible(0.3 + fishing_actions_delay):
            return False
        if sell_x > 0:
            _pyautogui_click(sell_x, sell_y)
        if not sleep_interruptible(0.3 + fishing_actions_delay):
            return False
        if confirm_x > 0:
            _pyautogui_click(confirm_x, confirm_y)
        if not sleep_interruptible(1.5 + fishing_actions_delay):
            return False

    if close_shop_x > 0:
        _pyautogui_click(close_shop_x, close_shop_y)
    if not sleep_interruptible(0.85 + fishing_actions_delay):
        return False

    if egg_ocr_check_cb is not None and bool(cfg.get("egg_ocr_detect_special", False)):
        try:
            egg_ocr_check_cb()
        except Exception as e:
            print(f"[Fishing] egg_ocr_check_cb error before final respawn: {e}")

    if not _run_respawn_sequence(
        sleep_interruptible=sleep_interruptible,
        should_continue=should_continue,
        can_run=can_run,
        action_delay_seconds=fishing_actions_delay,
        activate_roblox_cb=activate_roblox_cb,
    ):
        return False

    if not sleep_interruptible(0.2 + fishing_actions_delay):
        return False

    return True


def run_fishing_loop(
    *,
    stop_event: threading.Event | None = None,
    can_run_cb: Callable[[], bool] | None = None,
    config_provider: Callable[[], dict[str, Any]] | None = None,
    config_refresh_seconds: float = 2.0,
    log_prefix: str = "[Fishing]",
    print_start_stop: bool = True,
    on_failsafe_timeout: Callable[[], None] | None = None,
    run_br_sc_sequence_cb: Callable[[], bool] | None = None,
    run_merchant_sequence_cb: Callable[[], bool] | None = None,
    merchant_ocr_check_cb: Callable[[], None] | None = None,
    activate_roblox_cb: Callable[[], None] | None = None,
    close_chat_fn: Callable[[], None] | None = None,
    runtime_state: dict[str, Any] | None = None,
    set_fishing_busy_cb: Callable[[bool], None] | None = None,
    on_f2_pressed_cb: Callable[[], None] | None = None,
    egg_ocr_check_cb: Callable[[], None] | None = None,
) -> None:
    stop_event = stop_event or threading.Event()
    config_provider = config_provider or _load_config_file

    def _set_busy(busy: bool) -> None:
        if set_fishing_busy_cb is not None:
            try:
                set_fishing_busy_cb(busy)
            except Exception:
                pass

    def _notify_failsafe_timeout() -> None:
        if on_failsafe_timeout is None:
            return
        try:
            on_failsafe_timeout()
        except Exception:
            pass

    def _run_br_sc_sequence() -> bool:
        if run_br_sc_sequence_cb is None:
            return False
        try:
            return bool(run_br_sc_sequence_cb())
        except Exception:
            return False

    def _run_merchant_sequence() -> bool:
        if run_merchant_sequence_cb is None:
            return False
        try:
            return bool(run_merchant_sequence_cb())
        except Exception:
            return False

    def _should_continue() -> bool:
        return not stop_event.is_set()

    def _can_run() -> bool:
        if can_run_cb is None:
            return True
        try:
            return bool(can_run_cb())
        except Exception:
            return False

    def _sleep_interruptible(seconds: float, poll: float = 0.02) -> bool:
        end = time.monotonic() + max(0.0, float(seconds))
        while time.monotonic() < end:
            if not _should_continue() or not _can_run():
                return False
            remaining = end - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(poll, remaining))
        return _should_continue() and _can_run()

    def _get_due_actions() -> tuple[bool, int, bool, bool, bool]:
        sell_after = max(1, int(cfg.get("fishing_sell_after_x_fish", 30)))
        should_sell = bool(cfg.get("fishing_enable_selling", False)) and (fish_caught_count >= sell_after)
        sell_count = max(1, int(cfg.get("fishing_sell_how_many_fish", 1)))

        use_merchant_every_x = bool(cfg.get("fishing_use_merchant_every_x_fish", False))
        merchant_after = max(1, int(cfg.get("fishing_merchant_every_x_fish", 30)))
        should_use_merchant = use_merchant_every_x and (fish_caught_since_merchant >= merchant_after)

        use_merchant_ocr_every_x = bool(cfg.get("fishing_use_merchant_ocr_every_x_fish", False))
        merchant_ocr_after = max(1, int(cfg.get("fishing_merchant_ocr_every_x_fish_amt", 30)))
        should_use_merchant_ocr = use_merchant_ocr_every_x and (fish_caught_since_merchant_ocr >= merchant_ocr_after)

        use_br_sc_every_x = bool(cfg.get("fishing_use_br_sc_every_x_fish", False))
        br_sc_after = max(1, int(cfg.get("fishing_br_sc_every_x_fish", 30)))
        should_use_br_sc = use_br_sc_every_x and (fish_caught_since_br_sc >= br_sc_after)

        return should_sell, sell_count, should_use_merchant, should_use_br_sc, should_use_merchant_ocr

    cfg = load_fishing_config(config_provider())
    next_cfg_refresh_at = time.monotonic()
    was_runnable = False

    runtime_state_dict = runtime_state if isinstance(runtime_state, dict) else None

    def _state_counter(name: str) -> int:
        if runtime_state_dict is None:
            return 0
        try:
            value = int(runtime_state_dict.get(name, 0))
            return value if value >= 0 else 0
        except Exception:
            return 0

    def _state_flag(name: str) -> bool:
        if runtime_state_dict is None:
            return False
        try:
            return bool(runtime_state_dict.get(name, False))
        except Exception:
            return False

    def _set_state_flag(name: str, value: bool) -> None:
        if runtime_state_dict is None:
            return
        runtime_state_dict[name] = bool(value)

    def _consume_state_flag(name: str) -> bool:
        value = _state_flag(name)
        _set_state_flag(name, False)
        return value

    def _run_merchant_sequence_with_state() -> tuple[bool, bool]:
        ran = _run_merchant_sequence()
        return ran, _consume_state_flag("merchant_requires_reset")

    fish_caught_count = _state_counter("fish_caught_count")
    fish_caught_since_merchant = _state_counter("fish_caught_since_merchant")
    fish_caught_since_merchant_ocr = _state_counter("fish_caught_since_merchant_ocr")
    fish_caught_since_br_sc = _state_counter("fish_caught_since_br_sc")
    _set_state_flag("merchant_requires_reset", False)

    def _persist_runtime_counters() -> None:
        if runtime_state_dict is None:
            return
        runtime_state_dict["fish_caught_count"] = max(0, int(fish_caught_count))
        runtime_state_dict["fish_caught_since_merchant"] = max(0, int(fish_caught_since_merchant))
        runtime_state_dict["fish_caught_since_merchant_ocr"] = max(0, int(fish_caught_since_merchant_ocr))
        runtime_state_dict["fish_caught_since_br_sc"] = max(0, int(fish_caught_since_br_sc))

    _persist_runtime_counters()

    last_start_fishing_click_at: float | None = None
    sct = None
    if mss is not None:
        try:
            sct = mss.mss()
        except Exception:
            sct = None

    if print_start_stop:
        print(f"{log_prefix} started")
        print(f"{log_prefix} using calibration: {cfg}")
        print(
            f"{log_prefix} session fish counters: total={fish_caught_count}, "
            f"merchant={fish_caught_since_merchant}, br_sc={fish_caught_since_br_sc}"
        )

    try:
        while _should_continue():
            now = time.monotonic()
            if now >= next_cfg_refresh_at:
                try:
                    cfg = load_fishing_config(config_provider())
                except Exception:
                    cfg = load_fishing_config()
                next_cfg_refresh_at = now + max(0.2, float(config_refresh_seconds))

            if not _can_run():
                _set_busy(False)
                was_runnable = False
                last_start_fishing_click_at = None
                time.sleep(0.05)
                continue

            if not was_runnable:
                _set_busy(True)
                if close_chat_fn is not None:
                    try:
                        close_chat_fn()
                    except Exception as e:
                        print(f"{log_prefix} close_chat_fn error on resume: {e}")

                if _state_flag("force_sell_on_next_cycle"):
                    _set_state_flag("force_sell_on_next_cycle", False)
                    force_sell_count = max(1, int(cfg.get("fishing_sell_how_many_fish", 1)))
                    print(
                        f"{log_prefix} rejoin completed; forced selling flow before fishing path "
                        f"(selling {force_sell_count} fish)."
                    )
                    if not _run_sell_fish_sequence(
                        cfg=cfg,
                        fish_sell_count=force_sell_count,
                        sleep_interruptible=_sleep_interruptible,
                        should_continue=_should_continue,
                        can_run=_can_run,
                        activate_roblox_cb=activate_roblox_cb,
                        close_chat_fn=close_chat_fn,
                        set_busy_cb=_set_busy,
                        egg_ocr_check_cb=egg_ocr_check_cb,
                    ):
                        continue
                    fish_caught_count = 0
                    _persist_runtime_counters()
                    last_start_fishing_click_at = None
                    was_runnable = False
                    continue

                should_sell, sell_count, should_use_merchant, should_use_br_sc, should_use_merchant_ocr = _get_due_actions()

                if should_sell:
                    print(
                        f"{log_prefix} pending selling flow triggered before fishing path "
                        f"after {fish_caught_count} catches (selling {sell_count} fish)."
                    )
                    if not _run_sell_fish_sequence(
                        cfg=cfg,
                        fish_sell_count=sell_count,
                        sleep_interruptible=_sleep_interruptible,
                        should_continue=_should_continue,
                        can_run=_can_run,
                        activate_roblox_cb=activate_roblox_cb,
                        close_chat_fn=close_chat_fn,
                        set_busy_cb=_set_busy,
                        egg_ocr_check_cb=egg_ocr_check_cb,
                    ):
                        continue
                    fish_caught_count = 0
                    _persist_runtime_counters()

                    # Re-evaluate counters after selling because merchant/BRSC counters are independent.
                    _, _, should_use_merchant, should_use_br_sc, should_use_merchant_ocr = _get_due_actions()

                    if should_use_merchant:
                        print(f"{log_prefix} merchant flow triggered after pending selling.")
                        merchant_ran, _ = _run_merchant_sequence_with_state()
                        if merchant_ran:
                            fish_caught_since_merchant = 0
                        _persist_runtime_counters()
                        if not merchant_ran:
                            print(f"{log_prefix} merchant flow skipped/failed during fishing.")
                            
                    if should_use_merchant_ocr and merchant_ocr_check_cb is not None:
                        print(f"{log_prefix} merchant OCR triggered after pending selling.")
                        try:
                            _set_busy(True)
                            merchant_ocr_check_cb()
                        except Exception as e:
                            print(f"{log_prefix} merchant OCR check failure: {e}")
                        finally:
                            _set_busy(False)
                            fish_caught_since_merchant_ocr = 0
                            _persist_runtime_counters()

                    if should_use_br_sc:
                        print(f"{log_prefix} BR/SC flow triggered after pending selling.")
                        br_sc_ran = _run_br_sc_sequence()
                        if br_sc_ran:
                            fish_caught_since_br_sc = 0
                        _persist_runtime_counters()

                    last_start_fishing_click_at = None
                    was_runnable = False
                    continue

                if should_use_merchant:
                    print(
                        f"{log_prefix} pending merchant flow triggered before fishing path "
                        f"after {fish_caught_since_merchant} catches."
                    )
                    merchant_ran, _ = _run_merchant_sequence_with_state()
                    if merchant_ran:
                        fish_caught_since_merchant = 0
                    _persist_runtime_counters()
                    if not merchant_ran:
                        print(f"{log_prefix} merchant flow skipped/failed during fishing.")

                    if should_use_br_sc:
                        print(f"{log_prefix} BR/SC flow triggered after pending merchant.")
                        br_sc_ran = _run_br_sc_sequence()
                        if br_sc_ran:
                            fish_caught_since_br_sc = 0
                        _persist_runtime_counters()

                    last_start_fishing_click_at = None
                    was_runnable = False
                    continue
                    
                if should_use_merchant_ocr and merchant_ocr_check_cb is not None:
                    print(
                        f"{log_prefix} pending merchant OCR flow triggered before fishing path "
                        f"after {fish_caught_since_merchant_ocr} catches."
                    )
                    try:
                        _set_busy(True)
                        merchant_ocr_check_cb()
                    except Exception as e:
                        print(f"{log_prefix} merchant OCR check failure: {e}")
                    finally:
                        _set_busy(False)
                        fish_caught_since_merchant_ocr = 0
                        _persist_runtime_counters()
                        
                        
                    if should_use_br_sc:
                        print(f"{log_prefix} BR/SC flow triggered after merchant OCR.")
                        br_sc_ran = _run_br_sc_sequence()
                        if br_sc_ran:
                            fish_caught_since_br_sc = 0
                        _persist_runtime_counters()

                    last_start_fishing_click_at = None
                    was_runnable = False
                    continue

                if should_use_br_sc:
                    print(
                        f"{log_prefix} pending BR/SC flow triggered before fishing path "
                        f"after {fish_caught_since_br_sc} catches."
                    )
                    br_sc_ran = _run_br_sc_sequence()
                    if br_sc_ran:
                        fish_caught_since_br_sc = 0
                    _persist_runtime_counters()

                    last_start_fishing_click_at = None
                    was_runnable = False
                    continue

                if not _run_pre_fishing_sequence(
                    cfg=cfg,
                    sleep_interruptible=_sleep_interruptible,
                    should_continue=_should_continue,
                    can_run=_can_run,
                    activate_roblox_cb=activate_roblox_cb,
                    close_chat_fn=close_chat_fn,
                    egg_ocr_check_cb=egg_ocr_check_cb,
                ):
                    continue
                if not _run_equip_aura_before_movement(
                    cfg=cfg,
                    sleep_interruptible=_sleep_interruptible,
                    should_continue=_should_continue,
                    can_run=_can_run,
                ):
                    continue
                _non_vip = bool(cfg.get("non_vip_movement_path", False))
                _walk_multiplier = NON_VIP_WALK_SPEED_MULTIPLIER if _non_vip else 1.0
                _playback_mult = float(cfg.get("fishing_playback_multiplier", 1.0))
                _combined_multiplier = _walk_multiplier * _playback_mult
                if not _run_walk_to_fish_path(
                    cfg=cfg,
                    sleep_interruptible=_sleep_interruptible,
                    should_continue=_should_continue,
                    can_run=_can_run,
                    speed_multiplier=_combined_multiplier,
                ):
                    continue
                
                close_x, close_y = cfg["fishing_close_button_pos"]
                for _ in range(3):
                    _pyautogui_click(close_x, close_y)
                    if not _sleep_interruptible(0.15): break
                if not _sleep_interruptible(0.3): continue

                click_x, click_y = cfg["fishing_click_position"]
                _pyautogui_click(click_x, click_y)
                last_start_fishing_click_at = time.monotonic()
                if not _sleep_interruptible(0.25): continue
                was_runnable = True
                _set_busy(False)

            if (
                was_runnable
                and bool(cfg.get("fishing_failsafe_rejoin", False))
                and last_start_fishing_click_at is not None
                and (time.monotonic() - float(last_start_fishing_click_at)) >= 60.0
            ):
                print(f"{log_prefix} failsafe triggered: no minigame detected for >=60s. Closing Roblox.")
                _notify_failsafe_timeout()
                was_runnable = False
                last_start_fishing_click_at = None
                continue

            detect_x, detect_y = cfg["fishing_detect_pixel"]
            pixel = _get_pixel_rgb(detect_x, detect_y, sct=sct)
            if not is_indicator_active(pixel):
                time.sleep(float(cfg.get("fishing_idle_poll_sleep", 0.004)))
                continue

            _set_busy(True)
            click_x, click_y = cfg["fishing_click_position"]
            _pyautogui_click(click_x, click_y)
            last_start_fishing_click_at = time.monotonic()
            if not _sleep_interruptible(float(cfg.get("fishing_pre_reel_wait", 0.18))):
                continue

            if not _should_continue() or not _can_run():
                continue

            midbar_x, midbar_y = cfg["fishing_midbar_sample_pos"]
            bar_color = _get_pixel_rgb(midbar_x, midbar_y, sct=sct)
            start_time = time.time()

            while (time.time() - start_time) < 9:
                if not _should_continue() or not _can_run():
                    break
                found = detect_colour(
                    bar_color,
                    cfg["fishing_bar_region"],
                    tolerance=int(cfg.get("fishing_bar_color_tolerance", 12)),
                    scan_height=int(cfg.get("fishing_bar_scan_height", 3)),
                    sct=sct,
                )
                if not found:
                    click_burst = int(cfg.get("fishing_click_burst", 2))
                    for i in range(max(1, click_burst)):
                        _pyautogui_click(click_x, click_y)
                        if i + 1 < click_burst and not _sleep_interruptible(0.001):
                            break
                time.sleep(float(cfg.get("fishing_reel_loop_sleep", 0.004)))

            if not _should_continue() or not _can_run():
                continue

            if not _sleep_interruptible(1.0):
                continue

            close_x, close_y = cfg["fishing_close_button_pos"]
            for _ in range(5):
                _pyautogui_click(close_x, close_y)
                if not _sleep_interruptible(0.55):
                    break

            fish_caught_count += 1
            fish_caught_since_merchant += 1
            fish_caught_since_merchant_ocr += 1
            fish_caught_since_br_sc += 1
            _persist_runtime_counters()

            _set_busy(False)
            if not _sleep_interruptible(0.42): continue
            _set_busy(True)

            if not _should_continue() or not _can_run():
                continue

            use_merchant_every_x = bool(cfg.get("fishing_use_merchant_every_x_fish", False))
            merchant_after = max(1, int(cfg.get("fishing_merchant_every_x_fish", 30)))
            should_use_merchant = use_merchant_every_x and (fish_caught_since_merchant >= merchant_after)

            use_merchant_ocr_every_x = bool(cfg.get("fishing_use_merchant_ocr_every_x_fish", False))
            merchant_ocr_after = max(1, int(cfg.get("fishing_merchant_ocr_every_x_fish_amt", 30)))
            should_use_merchant_ocr = use_merchant_ocr_every_x and (fish_caught_since_merchant_ocr >= merchant_ocr_after)

            use_br_sc_every_x = bool(cfg.get("fishing_use_br_sc_every_x_fish", False))
            br_sc_after = max(1, int(cfg.get("fishing_br_sc_every_x_fish", 30)))
            should_use_br_sc = use_br_sc_every_x and (fish_caught_since_br_sc >= br_sc_after)

            if bool(cfg.get("fishing_enable_selling", False)):
                sell_after = int(cfg.get("fishing_sell_after_x_fish", 30))
                sell_count = int(cfg.get("fishing_sell_how_many_fish", 1))
                if fish_caught_count >= max(1, sell_after):
                    _set_busy(True)
                    print(
                        f"{log_prefix} selling flow triggered after {fish_caught_count} catches "
                        f"(selling {max(1, sell_count)} fish)."
                    )
                    if not _run_sell_fish_sequence(
                        cfg=cfg,
                        fish_sell_count=max(1, sell_count),
                        sleep_interruptible=_sleep_interruptible,
                        should_continue=_should_continue,
                        can_run=_can_run,
                        activate_roblox_cb=activate_roblox_cb,
                        close_chat_fn=close_chat_fn,
                        set_busy_cb=_set_busy,
                    ):
                        continue
                    fish_caught_count = 0
                    _persist_runtime_counters()

                    if should_use_merchant:
                        print(f"{log_prefix} merchant flow triggered after selling.")
                        merchant_ran, _ = _run_merchant_sequence_with_state()
                        if merchant_ran:
                            fish_caught_since_merchant = 0
                        _persist_runtime_counters()
                        if not merchant_ran:
                            print(f"{log_prefix} merchant flow skipped/failed during fishing.")

                    if should_use_merchant_ocr and merchant_ocr_check_cb is not None:
                        print(f"{log_prefix} merchant OCR triggered after selling.")
                        try:
                            merchant_ocr_check_cb()
                        except Exception as e:
                            print(f"{log_prefix} merchant OCR check failure: {e}")
                        finally:
                            fish_caught_since_merchant_ocr = 0
                            _persist_runtime_counters()

                    if should_use_br_sc:
                        print(f"{log_prefix} BR/SC flow triggered after selling.")
                        br_sc_ran = _run_br_sc_sequence()
                        if br_sc_ran:
                            fish_caught_since_br_sc = 0
                        _persist_runtime_counters()

                    was_runnable = False
                    last_start_fishing_click_at = None
                    _set_busy(False)
                    continue

            if should_use_merchant:
                print(f"{log_prefix} merchant flow triggered after {fish_caught_since_merchant} catches.")
                merchant_ran, merchant_requires_reset = _run_merchant_sequence_with_state()
                if merchant_ran:
                    fish_caught_since_merchant = 0
                _persist_runtime_counters()
                if not merchant_ran:
                    print(f"{log_prefix} merchant flow skipped/failed during fishing.")

                if should_use_merchant_ocr and merchant_ocr_check_cb is not None:
                    print(f"{log_prefix} merchant OCR triggered after merchant flow.")
                    try:
                        merchant_ocr_check_cb()
                    except Exception as e:
                        print(f"{log_prefix} merchant OCR check failure: {e}")
                    finally:
                        fish_caught_since_merchant_ocr = 0
                        _persist_runtime_counters()

                if should_use_br_sc:
                    print(f"{log_prefix} BR/SC flow triggered after merchant.")
                    br_sc_ran = _run_br_sc_sequence()
                    if br_sc_ran:
                        fish_caught_since_br_sc = 0
                    should_use_br_sc = False
                    _persist_runtime_counters()

                if merchant_requires_reset:
                    if not _sleep_interruptible(0.4 + _get_fishing_actions_delay_seconds(cfg)):
                        continue
                    was_runnable = False
                    last_start_fishing_click_at = None
                    continue

            if should_use_merchant_ocr and merchant_ocr_check_cb is not None:
                print(f"{log_prefix} merchant OCR triggered after {fish_caught_since_merchant_ocr} catches.")
                try:
                    merchant_ocr_check_cb()
                except Exception as e:
                    print(f"{log_prefix} merchant OCR check failure: {e}")
                finally:
                    fish_caught_since_merchant_ocr = 0
                    _persist_runtime_counters()

            if should_use_br_sc:
                print(f"{log_prefix} BR/SC flow triggered after {fish_caught_since_br_sc} catches.")
                br_sc_ran = _run_br_sc_sequence()
                if br_sc_ran:
                    fish_caught_since_br_sc = 0
                _persist_runtime_counters()

            start_x, start_y = cfg["fishing_click_position"]
            _pyautogui_click(start_x, start_y)
            last_start_fishing_click_at = time.monotonic()
            _sleep_interruptible(0.3)
            _set_busy(False)
    finally:
        _set_busy(False)
        
        for k in ("w", "a", "s", "d", "space"):
            try:
                _pyautogui_key_up(k)
            except Exception:
                pass
            
        if sct is not None:
            try:
                sct.close()
            except Exception:
                pass
        if print_start_stop:
            print(f"{log_prefix} stopped")

def main():
    try:
        run_fishing_loop()
    except KeyboardInterrupt:
        print("[Fishing] stopped by keyboard interrupt")


if __name__ == "__main__":
    main()

print("Sven is sick")