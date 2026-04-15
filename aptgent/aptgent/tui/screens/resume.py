from __future__ import annotations

from datetime import datetime
from typing import Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Vertical
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from aptgent.workflow.context import build_run_overview
from aptgent.workflow.state import RunState


def _step_label(state: RunState) -> str:
    return state.current_step.value.replace("_", " ").title()


def _shorten(text: str, limit: int) -> str:
    clean = " ".join(text.split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1] + "…"


def _overview(state: RunState) -> str:
    parts = build_run_overview(state).split(" | ")
    shortened: list[str] = []
    for index, part in enumerate(parts):
        limit = 28 if index == 0 else 18 if index == 1 else 36
        shortened.append(_shorten(part, limit))
    summary = " | ".join(shortened) if shortened else "Untitled run"
    return f"{summary} - {_step_label(state)}"


def _timestamp_label(state: RunState) -> str:
    raw = state.updated_at or state.created_at
    try:
        stamp = datetime.fromisoformat(raw).astimezone().strftime("%Y-%m-%d %H:%M")
    except Exception:
        stamp = raw
    return f"{stamp} - {state.run_id}"


def list_resume_candidates(app) -> list[RunState]:
    states: list[RunState] = []
    for run_id in app.persistence.list_runs():
        state = app.persistence.load(run_id)
        if state is not None:
            states.append(state)
    states.sort(key=lambda item: item.updated_at or item.created_at, reverse=True)
    return states


class ResumePickerScreen(ModalScreen[Optional[str]]):
    """Modal selector for switching to a saved run."""

    BINDINGS = [
        Binding("escape", "cancel", "Close"),
        Binding("q", "cancel", "Close"),
    ]

    CSS = """
    ResumePickerScreen {
        align: center middle;
        background: $background 60%;
    }
    #resume-shell {
        width: 104;
        max-width: 96%;
        height: auto;
        background: $surface-darken-2;
        border: round $primary;
        padding: 2 3;
    }
    #resume-kicker {
        color: $text-muted;
        margin-bottom: 1;
    }
    #resume-title {
        text-style: bold;
        color: $primary-lighten-2;
    }
    #resume-subtitle {
        color: $text-muted;
        margin-top: 1;
        margin-bottom: 1;
    }
    #resume-run-list {
        height: 12;
        border: tall $surface-lighten-1;
        margin-top: 1;
    }
    #resume-empty {
        color: $text-muted;
        margin-top: 1;
    }
    """

    def compose(self) -> ComposeResult:
        states = list_resume_candidates(self.app)
        with Center():
            with Vertical(id="resume-shell"):
                yield Static("RESUME RUN", id="resume-kicker")
                yield Static("Saved Workflows", id="resume-title")
                yield Static(
                    "Use Up/Down and Enter to reopen a saved workflow state.",
                    id="resume-subtitle",
                )
                if states:
                    options = [
                        Option(
                            f"[bold]{_overview(state)}[/bold]\n[dim]{_timestamp_label(state)}[/dim]",
                            id=state.run_id,
                        )
                        for state in states
                    ]
                    yield OptionList(*options, id="resume-run-list")
                else:
                    yield Static("No saved runs available.", id="resume-empty")

    def on_mount(self) -> None:
        self.call_after_refresh(self._focus_default)

    def _focus_default(self) -> None:
        try:
            self.query_one("#resume-run-list", OptionList).focus()
        except Exception:
            pass

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id != "resume-run-list":
            return
        run_id = event.option.id
        self.dismiss(run_id if run_id else None)
