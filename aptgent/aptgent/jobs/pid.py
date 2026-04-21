# aptgent/aptgen/jobs/pid.py
"""PID file management and liveness checks for detached workers.

Linux-only: uses ``os.kill(pid, 0)`` for liveness check.
"""
from __future__ import annotations

import os
from pathlib import Path


def read_pid(path: Path) -> int | None:
    """Read a PID from *path*, returning ``None`` if missing or invalid."""
    if not path.exists():
        return None
    try:
        text = path.read_text().strip()
        return int(text)
    except (ValueError, OSError):
        return None


def write_pid(path: Path, pid: int) -> None:
    """Write *pid* to *path*, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(pid))


def clear_pid(path: Path) -> None:
    """Remove the PID file if it exists."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def is_pid_alive(pid: int) -> bool:
    """Check whether *pid* refers to a running process.

    Uses ``os.kill(pid, 0)``. Returns ``False`` on any error.
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we can't signal it — still alive
        pass
    except OSError:
        return False
    return True
