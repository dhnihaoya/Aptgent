# aptgent/aptgent/jobs/pid.py
"""PID file management and liveness checks for detached workers.

Linux-only: uses ``os.kill(pid, 0)`` for liveness check.
"""
from __future__ import annotations

import os
import signal
import time
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


def clear_pid(path: Path, pid: int | None = None) -> None:
    """Remove the PID file if it exists and matches *pid*.

    If *pid* is given, the file is only removed when it still contains that
    exact PID value.  This prevents an old atexit handler from deleting a
    PID file that a newer process has already claimed.
    """
    try:
        if pid is not None:
            current = read_pid(path)
            if current is not None and current != pid:
                return
        path.unlink(missing_ok=True)
    except OSError:
        pass


def kill_pid(
    pid: int, *, sigterm_timeout: float = 3, sigkill_timeout: float = 5,
) -> bool:
    """Terminate a process: SIGTERM -> wait -> SIGKILL -> wait.

    Returns ``True`` if the process was successfully killed or was already gone.
    """
    if not is_pid_alive(pid):
        return True

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    except OSError:
        return False

    deadline = time.monotonic() + sigterm_timeout
    while time.monotonic() < deadline:
        if not is_pid_alive(pid):
            return True
        time.sleep(0.2)

    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return True
    except OSError:
        return False

    deadline = time.monotonic() + sigkill_timeout
    while time.monotonic() < deadline:
        if not is_pid_alive(pid):
            return True
        time.sleep(0.2)

    return not is_pid_alive(pid)


def is_pid_alive(pid: int) -> bool:
    """Check whether *pid* refers to a running process.

    Uses ``os.kill(pid, 0)`` and excludes zombies via ``/proc/<pid>/stat``.
    Returns ``False`` on any error.
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
    # Exclude zombies — they're dead but os.kill(pid,0) still succeeds.
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        state = stat[stat.rindex(")") + 1:].split()[0]
        return state not in ("Z", "z")
    except (OSError, IndexError):
        return True
