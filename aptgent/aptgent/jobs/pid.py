# aptgent/aptgent/jobs/pid.py
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


def write_pid(path: Path, pid: int, *, force: bool = False) -> bool:
    """Write *pid* to *path* atomically.

    Uses ``O_CREAT | O_EXCL`` so two processes cannot race to create the file.
    If the file already exists and the existing PID is still alive, returns
    ``False`` without overwriting (unless *force* is ``True``).

    Returns ``True`` on success.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists() and not force:
        existing = read_pid(path)
        if existing is not None and is_pid_alive(existing):
            return False
        # Stale — remove so O_EXCL can succeed
        try:
            path.unlink()
        except OSError:
            pass

    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return False

    try:
        os.write(fd, str(pid).encode())
    finally:
        os.close(fd)
    return True


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
