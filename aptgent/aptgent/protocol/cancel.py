"""Cancellation primitives for subprocess and detached-job coordination."""

from __future__ import annotations

import threading
from pathlib import Path


class StdinCancelWatcher:
    """Daemon thread that watches stdin for a cancel token.

    Sets ``cancel_event`` when the token (default ``"cancel"``) is received.
    """

    def __init__(
        self,
        cancel_event: threading.Event,
        *,
        token: str = "cancel",
    ) -> None:
        import sys

        self._cancel_event = cancel_event
        self._token = token
        self._stdin = sys.stdin
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            for line in self._stdin:
                if line.strip() == self._token:
                    self._cancel_event.set()
                    break
        except Exception:
            pass

    def join(self, timeout: float = 2) -> None:
        self._thread.join(timeout=timeout)


class CmdFileCancelPoller:
    """Polls a command file for cancel instructions.

    When the file exists and contains ``"cancel"``, sets *cancel_event*.
    The poller runs on a daemon thread that exits when *stop_event* is set
    or *cancel_event* is set.
    """

    def __init__(
        self,
        cmd_file: Path,
        cancel_event: threading.Event,
        stop_event: threading.Event,
        *,
        interval: float = 2,
    ) -> None:
        self._cmd_file = cmd_file
        self._cancel_event = cancel_event
        self._stop_event = stop_event
        self._interval = interval
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop_event.is_set() and not self._cancel_event.is_set():
            if self._cmd_file.exists():
                try:
                    content = self._cmd_file.read_text().strip()
                    if content == "cancel":
                        self._cancel_event.set()
                        return
                except OSError:
                    pass
            self._stop_event.wait(self._interval)

    def join(self, timeout: float = 2) -> None:
        self._thread.join(timeout=timeout)
