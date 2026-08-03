# Lightweight stub for `keyboard` to avoid requiring Accessibility on macOS.
# This file intentionally shadows the third-party `keyboard` package when running
# the app from the repository. It provides safe no-op implementations for the
# functions the app uses so the process doesn't spawn background listeners.

import platform

if platform.system() == 'Darwin':
    def add_hotkey(hotkey, callback, suppress=False):
        print(f"[keyboard stub] Skipping hotkey binding on macOS: {hotkey}")

    def remove_hotkey(hotkey):
        return False

    def write(*args, **kwargs):
        return None

    def is_pressed(key):
        return False

    def press(key):
        return None

    def release(key):
        return None

    # minimal compatibility: expose attributes consumed by some modules
    __all__ = ["add_hotkey", "remove_hotkey", "write", "is_pressed", "press", "release"]
else:
    # On non-mac platforms, prefer the real package — try to import and fall back to stub.
    try:
        from keyboard import *  # type: ignore
    except Exception:
        def add_hotkey(hotkey, callback, suppress=False):
            print(f"[keyboard stub] add_hotkey fallback (no-op): {hotkey}")
        def remove_hotkey(hotkey):
            return False
        def write(*args, **kwargs):
            return None
        def is_pressed(key):
            return False
        def press(key):
            return None
        def release(key):
            return None
        __all__ = ["add_hotkey", "remove_hotkey", "write", "is_pressed", "press", "release"]
