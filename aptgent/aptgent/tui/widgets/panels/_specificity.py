from __future__ import annotations

import logging

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.css.query import NoMatches
from textual.widgets import Button, Input, SelectionList, Static

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
        width: 100%;
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
        self.confirm_button = Button(
            "Confirm Selection",
            id="btn-confirm-analogs",
            variant="success",
        )
        yield self.confirm_button

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


class SpecificityPanel(_BaseStructuredPanel):
    """Inline widget for specificity filter input."""

    DEFAULT_CSS = """
    SpecificityPanel > .panel-help {
        margin: 1 0;
    }
    SpecificityPanel > Input {
        margin: 1 0;
    }
    SpecificityPanel Horizontal {
        height: auto;
    }
    SpecificityPanel Horizontal > Button {
        margin-right: 1;
    }
    """

    def __init__(
        self,
        target_name: str = "",
        analogs_text: str = "",
        *,
        title: str = "Specificity Filter",
        help_text: str = "Enter analog molecules for cross-screening. Use commas between names or SMILES.",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.target_name = target_name
        self.analogs_text = analogs_text
        self.title = title
        self.help_text = help_text

    def compose(self) -> ComposeResult:
        yield Static(self.title, classes="panel-title")
        if self.target_name:
            yield Static(f"Target: [bold]{self.target_name}[/]")
        yield Static(self.help_text, classes="panel-help")
        analog_input = Input(
            id="analog-input",
            placeholder="e.g. adenine, hypoxanthine",
        )
        analog_input.value = self.analogs_text
        yield analog_input
        with Horizontal():
            yield Button("Run Filter", id="btn-run-filter", variant="warning")
            yield Button("Skip", id="btn-skip-filter")

    def on_mount(self) -> None:
        try:
            self.query_one("#analog-input", Input).focus()
        except NoMatches:
            _log.debug("Focus target missing during on_mount", exc_info=True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "btn-run-filter":
            analogs = self.query_one("#analog-input", Input).value.strip()
            self.post_message(
                StructuredInputSubmitted(
                    Step.SPECIFICITY_FILTER,
                    {"action": "run", "analogs_text": analogs},
                )
            )
        elif btn_id == "btn-skip-filter":
            self.post_message(
                StructuredInputSubmitted(
                    Step.SPECIFICITY_FILTER,
                    {"action": "skip"},
                )
            )


class AnalogCustomPanel(_BaseStructuredPanel):
    """Natural-language analog entry with LLM parsing and confirmation."""

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
        title: str = "Custom Specificity Analogs",
        help_text: str = "Describe the analogs you want in natural language.",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.target_name = target_name
        self.title = title
        self.help_text = help_text
        self._resolved_analogs_text: str = ""
        self._resolved_pairs: list[tuple[str, bool]] = []

    def compose(self) -> ComposeResult:
        yield Static(self.title, classes="panel-title")
        if self.target_name:
            yield Static(f"Target: [bold]{self.target_name}[/]")
        yield Static(self.help_text, classes="panel-help")
        yield Input(
            id="custom-analog-input",
            placeholder="e.g. just caffeine is fine",
        )
        with Horizontal():
            yield Button("Parse My Request", id="btn-parse-custom", variant="primary")
            yield Button("Skip", id="btn-skip-custom")

    def on_mount(self) -> None:
        try:
            self.query_one("#custom-analog-input", Input).focus()
        except NoMatches:
            _log.debug("Focus target missing during on_mount", exc_info=True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "btn-parse-custom":
            text = self.query_one("#custom-analog-input", Input).value.strip()
            self.post_message(
                StructuredInputSubmitted(
                    Step.SPECIFICITY_FILTER,
                    {"action": "parse_custom", "custom_text": text},
                )
            )
        elif btn_id == "btn-skip-custom":
            self.post_message(
                StructuredInputSubmitted(
                    Step.SPECIFICITY_FILTER,
                    {"action": "skip"},
                )
            )
        elif btn_id == "btn-confirm-custom":
            self.post_message(
                StructuredInputSubmitted(
                    Step.SPECIFICITY_FILTER,
                    {"action": "run", "analogs_text": self._resolved_analogs_text},
                )
            )
        elif btn_id == "btn-retry-custom":
            self._reset_to_input_mode()

    def show_confirmation(self, resolved_pairs: list[tuple[str, bool]]) -> None:
        self._resolved_pairs = resolved_pairs
        resolved_names = [name for name, ok in resolved_pairs if ok]
        self._resolved_analogs_text = ", ".join(resolved_names)

        for child in list(self.children):
            child.remove()

        self.mount(Static("Parsed Analogs", classes="panel-title"))
        lines: list[str] = []
        for name, ok in resolved_pairs:
            if ok:
                lines.append(f"  [green]\u2713[/green] {name}")
            else:
                lines.append(f"  [red]\u2717[/red] {name} (could not resolve)")
        if lines:
            self.mount(Static("\n".join(lines), classes="resolved-list"))
        with Horizontal():
            self.mount(Button("Confirm and Run", id="btn-confirm-custom", variant="success"))
            self.mount(Button("Try Again", id="btn-retry-custom"))
        try:
            self.query_one("#btn-confirm-custom", Button).focus()
        except NoMatches:
            _log.debug("Focus target missing after confirmation mount", exc_info=True)

    def _reset_to_input_mode(self) -> None:
        self._resolved_pairs = []
        self._resolved_analogs_text = ""
        for child in list(self.children):
            child.remove()

        self.mount(Static(self.title, classes="panel-title"))
        if self.target_name:
            self.mount(Static(f"Target: [bold]{self.target_name}[/]"))
        self.mount(Static(self.help_text, classes="panel-help"))
        self.mount(Input(
            id="custom-analog-input",
            placeholder="e.g. just caffeine is fine",
        ))
        with Horizontal():
            self.mount(Button("Parse My Request", id="btn-parse-custom", variant="primary"))
            self.mount(Button("Skip", id="btn-skip-custom"))
        try:
            self.query_one("#custom-analog-input", Input).focus()
        except NoMatches:
            _log.debug("Focus target missing after retry mount", exc_info=True)
