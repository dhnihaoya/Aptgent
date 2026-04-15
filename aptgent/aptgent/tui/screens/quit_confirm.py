from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class QuitConfirmScreen(ModalScreen[bool]):
    """Confirmation modal for exiting the app."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("q", "cancel", "Cancel"),
    ]

    CSS = """
    QuitConfirmScreen {
        align: center middle;
        background: $background 60%;
    }
    #quit-shell {
        width: 72;
        max-width: 92%;
        height: auto;
        background: $surface-darken-2;
        border: round $error;
        padding: 2 3;
    }
    #quit-kicker {
        color: $error-lighten-1;
        text-style: bold;
        margin-bottom: 1;
    }
    #quit-title {
        color: $text;
        text-style: bold;
        margin-bottom: 1;
    }
    #quit-body {
        color: $text-muted;
        margin-bottom: 2;
    }
    #quit-actions {
        height: auto;
        align-horizontal: right;
    }
    #quit-cancel {
        min-width: 14;
        margin-right: 1;
    }
    #quit-confirm {
        min-width: 16;
    }
    """

    def compose(self) -> ComposeResult:
        with Center():
            with Vertical(id="quit-shell"):
                yield Static("EXIT", id="quit-kicker")
                yield Static("Exit Aptgent?", id="quit-title")
                yield Static(
                    "Your current progress will stay on disk. Close the app now?",
                    id="quit-body",
                )
                with Horizontal(id="quit-actions"):
                    yield Button("Cancel", id="quit-cancel")
                    yield Button("Quit Aptgent", id="quit-confirm", variant="error")

    def action_cancel(self) -> None:
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "quit-confirm":
            self.dismiss(True)
        elif event.button.id == "quit-cancel":
            self.dismiss(False)
