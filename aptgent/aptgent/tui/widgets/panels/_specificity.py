from __future__ import annotations

import logging

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.css.query import NoMatches
from textual.widgets import Button, SelectionList, Static

from aptgent.domain.enums import Step

from ._core import StructuredInputSubmitted, _BaseStructuredPanel

_log = logging.getLogger(__name__)


class AnalogCheckboxPanel(_BaseStructuredPanel):
    """Checkbox panel for toggling individual recommended analogs."""

    DEFAULT_CSS = """
    AnalogCheckboxPanel > SelectionList {
        height: auto;
        max-height: 12;
        border: tall $surface-lighten-1;
    }
    AnalogCheckboxPanel > Button {
        margin-top: 1;
        margin-right: 1;
    }
    AnalogCheckboxPanel Horizontal {
        height: auto;
    }
    """

    def __init__(
        self,
        analog_names: list[str],
        *,
        target_name: str = "",
        title: str = "Select Analogs for Specificity Filter",
        help_text: str = "Use Up/Down to move, Space to toggle, Enter to confirm.",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.analog_names = analog_names
        self.target_name = target_name
        self.title = title
        self.help_text = help_text
        self.selection_list: SelectionList[str] | None = None
        self.confirm_button: Button | None = None

    def compose(self) -> ComposeResult:
        yield Static(self.title, classes="panel-title")
        if self.target_name:
            yield Static(f"Target: [bold]{self.target_name}[/]")
        yield Static(self.help_text, classes="panel-help")
        selections = [
            (f"[bold]{name}[/bold]", name, True)
            for name in self.analog_names
        ]
        self.selection_list = SelectionList(*selections, id="analog-selection-list")
        yield self.selection_list
        with Horizontal():
            self.confirm_button = Button(
                "Confirm Selection",
                id="btn-confirm-analogs",
                variant="success",
            )
            yield self.confirm_button
            yield Button("Back", id="btn-back-analogs")

    def on_mount(self) -> None:
        if self.selection_list is not None:
            self.selection_list.focus()

    def on_selection_list_selected_changed(self, event: SelectionList.SelectedChanged) -> None:
        event.stop()
        if self.confirm_button is not None and self.selection_list is not None:
            self.confirm_button.disabled = not self.selection_list.selected

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-confirm-analogs" and self.selection_list is not None:
            selected = ", ".join(self.selection_list.selected)
            self.post_message(
                StructuredInputSubmitted(
                    Step.SPECIFICITY_FILTER,
                    {"action": "run", "analogs_text": selected},
                )
            )
        elif event.button.id == "btn-back-analogs":
            self.post_message(
                StructuredInputSubmitted(
                    Step.SPECIFICITY_FILTER,
                    {"action": "back"},
                )
            )


class AnalogCustomPanel(_BaseStructuredPanel):
    """Confirmation panel for LLM-parsed analog results.

    Renders a resolved/unresolved list with Confirm/Try Again buttons.
    Always constructed with ``resolved_pairs`` from ``_parse_custom_worker``.
    """

    DEFAULT_CSS = """
    AnalogCustomPanel > .panel-help {
        margin: 1 0;
    }
    AnalogCustomPanel > Input {
        margin: 1 0;
    }
    AnalogCustomPanel Horizontal {
        height: auto;
    }
    AnalogCustomPanel Horizontal > Button {
        margin-right: 1;
    }
    AnalogCustomPanel > .resolved-list {
        margin: 1 0;
    }
    """

    def __init__(
        self,
        *,
        target_name: str = "",
        resolved_pairs: list[tuple[str, bool]] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.target_name = target_name
        self.resolved_pairs = resolved_pairs
        resolved_names = [name for name, ok in (resolved_pairs or []) if ok]
        self._resolved_analogs_text = ", ".join(resolved_names)

    def compose(self) -> ComposeResult:
        yield Static("Parsed Analogs", classes="panel-title")
        lines: list[str] = []
        for name, ok in (self.resolved_pairs or []):
            if ok:
                lines.append(f"  [green]\u2713[/green] {name}")
            else:
                lines.append(f"  [red]\u2717[/red] {name} (could not resolve)")
        if lines:
            yield Static("\n".join(lines), classes="resolved-list")
        with Horizontal():
            yield Button("Confirm and Run", id="btn-confirm-custom", variant="success")
            yield Button("Try Again", id="btn-retry-custom")

    def on_mount(self) -> None:
        try:
            self.query_one("#btn-confirm-custom", Button).focus()
        except NoMatches:
            _log.debug("Focus target missing during on_mount", exc_info=True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "btn-confirm-custom":
            self.post_message(
                StructuredInputSubmitted(
                    Step.SPECIFICITY_FILTER,
                    {"action": "run", "analogs_text": self._resolved_analogs_text},
                )
            )
        elif btn_id == "btn-retry-custom":
            self.post_message(
                StructuredInputSubmitted(
                    Step.SPECIFICITY_FILTER,
                    {"action": "retry_custom"},
                )
            )
