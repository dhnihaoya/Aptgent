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
        """Run a step worker with a visible activity status."""
        self.screen.show_activity(activity)
        self.screen.set_input_enabled(False)
        self.screen.run_worker(work, exclusive=True, thread=True)
