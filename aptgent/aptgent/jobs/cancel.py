# aptgent/aptgent/jobs/cancel.py
"""Cancel polling context for job runners.

Wraps :class:`CmdFileCancelPoller` and a ``threading.Event`` so that each
runner can use a single ``with``-block instead of duplicating the same
setup / teardown boilerplate.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from aptgent.protocol.cancel import CmdFileCancelPoller

if TYPE_CHECKING:
    pass

_log = logging.getLogger(__name__)


class CancelContext:
    """Cooperative cancellation via a command-file poller.

    Usage::

        with CancelContext(cmd_file) as ctx:
            for item in work:
                if ctx.cancelled:
                    break
                process(item)
    """

    def __init__(self, cmd_file: Path, *, interval: float = 2) -> None:
        self._cancel_event = threading.Event()
        self._stop_poller = threading.Event()
        self._poller = CmdFileCancelPoller(
            cmd_file, self._cancel_event, self._stop_poller, interval=interval,
        )

    # -- context manager protocol -----------------------------------------

    def __enter__(self) -> CancelContext:
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop_poller.set()
        self._poller.join(timeout=2)

    # -- public API -------------------------------------------------------

    @property
    def cancel_event(self) -> threading.Event:
        """The underlying ``threading.Event`` that is set on cancellation."""
        return self._cancel_event

    @property
    def cancelled(self) -> bool:
        """``True`` once the cancel command has been received."""
        return self._cancel_event.is_set()
