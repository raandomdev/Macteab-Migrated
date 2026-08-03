from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Optional


def should_block_start(
    lockfile_path: Path | str,
    *,
    pid_exists: Optional[Callable[[int], bool]] = None,
    force: bool = False,
) -> bool:
    """Return True when another live instance appears to be running."""
    if force:
        return False

    path = Path(lockfile_path)
    if not path.exists():
        return False

    try:
        raw_value = path.read_text(encoding="utf-8").strip()
        pid = int(raw_value)
    except (OSError, ValueError, TypeError):
        return False

    if pid <= 0:
        return False

    if pid_exists is None:
        try:
            import psutil
        except Exception:
            return False
        pid_exists = psutil.pid_exists

    return bool(pid_exists(pid))


def clear_stale_lockfile(lockfile_path: Path | str) -> bool:
    """Remove a lockfile when it points to a dead PID or contains invalid data."""
    path = Path(lockfile_path)
    if not path.exists():
        return False

    try:
        raw_value = path.read_text(encoding="utf-8").strip()
        pid = int(raw_value)
    except (OSError, ValueError, TypeError):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            return False
        return True

    if pid <= 0:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            return False
        return True

    try:
        import psutil
    except Exception:
        return False

    if psutil.pid_exists(pid):
        return False

    try:
        path.unlink(missing_ok=True)
    except OSError:
        return False
    return True
