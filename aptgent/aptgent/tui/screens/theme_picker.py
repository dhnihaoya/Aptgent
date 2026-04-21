from __future__ import annotations

import logging

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Vertical
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from aptgent.tui.commands import THEME_PRESETS

_log = logging.getLogger(__name__)


class ThemePickerScreen(ModalScreen):
    """Modal selector for switching among built-in UI themes."""

    BINDINGS = [
        Binding("escape", "cancel", "Close"),
        Binding("q", "cancel", "Close"),
    ]

    CSS = """
    ThemePickerScreen {
        align: center middle;
        background: $background 60%;
    }
    #theme-shell {
        width: 92;
        max-width: 96%;
        height: auto;
        background: $surface-darken-2;
        border: round $primary;
        padding: 2 3;
    }
    #theme-kicker {
        color: $text-muted;
        margin-bottom: 1;
    }
    #theme-title {
        text-style: bold;
        color: $primary-lighten-2;
    }
    #theme-subtitle {
        color: $text-muted;
        margin-top: 1;
        margin-bottom: 1;
    }
    #theme-option-list {
        height: 10;
        border: tall $surface-lighten-1;
        margin-top: 1;
    }
    """

    def compose(self) -> ComposeResult:
        options = [
            Option(
                f"[bold]{preset.label}[/bold]\n[dim]{preset.description}[/dim]",
                id=preset.theme_name,
            )
            for preset in THEME_PRESETS
        ]
        with Center():
            with Vertical(id="theme-shell"):
                yield Static("THEME", id="theme-kicker")
                yield Static("Choose a Theme", id="theme-title")
                yield Static(
                    "Use Up/Down and Enter to switch the active color theme.",
                    id="theme-subtitle",
                )
                yield OptionList(*options, id="theme-option-list")

    def on_mount(self) -> None:
        self.call_after_refresh(self._focus_default)

    def _focus_default(self) -> None:
        try:
            self.query_one("#theme-option-list", OptionList).focus()
        except NoMatches:
            _log.debug("theme-option-list not mounted", exc_info=True)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id != "theme-option-list":
            return
        theme_name = event.option.id
        self.dismiss(theme_name if theme_name else None)
