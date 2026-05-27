from __future__ import annotations

from typing import Any, Callable


class StepHandler:
    """Base class for per-step handlers."""

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
                self.screen.app.call_from_thread(self.screen.set_input_enabled, True)

        self.screen.run_worker(_guarded, exclusive=True, thread=True)
