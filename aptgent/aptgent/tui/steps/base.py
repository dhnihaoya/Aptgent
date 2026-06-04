from __future__ import annotations

from typing import Any, Callable


class StepHandler:
    """Base class for per-step handlers."""

    allow_empty_input: bool = False

    def __init__(self, screen: Any) -> None:
        self.screen = screen

    def enter(self) -> None:
        """Called when the step becomes active."""
        ...

    def handle_user_input(self, text: str) -> None:
        """Called when the user submits free-text input."""
        ...

    def handle_structured_input(self, data: dict) -> None:
        """Called when a structured panel submits data."""
        ...

    def handle_action(self, action: str) -> None:
        """Called when a structured panel requests an action."""
        ...

    def run_worker(self, work: Callable[[], Any], *, activity: str) -> None:
        """Run a step worker with a visible activity status.

        Input is disabled while the worker runs and re-enabled when it
        finishes (even on error).
        """
        self.screen.show_activity(activity)
        self.screen.set_input_enabled(False)

        def _guarded() -> None:
            try:
                work()
            finally:
                self._enable_input()

        self.screen.run_worker(_guarded, exclusive=True, thread=True)

    def _threadsafe(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        """Schedule *fn* on the main Textual thread."""
        self.screen.app.call_from_thread(fn, *args, **kwargs)

    def _enable_input(self) -> None:
        """Re-enable the input bar from a worker thread."""
        self._threadsafe(self.screen.set_input_enabled, True)

    def _report_error(self, message: str, *, style: str = "error-text") -> None:
        """Show a failure message and re-enable input.

        Combines the ``add_system_message`` + ``_enable_input`` pair that
        otherwise recurs in worker error handlers, so a forgotten
        ``_enable_input`` can no longer leave the input bar disabled.
        """
        self._threadsafe(self.screen.add_system_message, message, style)
        self._enable_input()
