from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Input, Static


class WelcomeScreen(Screen):
    """Entry screen: create a new run."""

    BINDINGS = [
        Binding("n", "new_run", "New Run"),
        Binding("q", "quit", "Quit"),
    ]

    CSS = """
    WelcomeScreen {
        layout: vertical;
        align: center middle;
        padding: 1 2;
    }
    #welcome-shell {
        width: 104;
        max-width: 96%;
        height: auto;
    }
    #welcome-hero {
        background: $surface-darken-2;
        border: round $primary;
        padding: 2 3;
        margin-bottom: 1;
        height: auto;
    }
    #welcome-kicker {
        color: $text-muted;
        margin-bottom: 1;
    }
    #welcome-title {
        text-style: bold;
        color: $primary-lighten-2;
    }
    #welcome-subtitle {
        color: $text-muted;
        margin-top: 1;
    }
    #welcome-body {
        height: auto;
    }
    .welcome-card {
        background: $surface-darken-1;
        border: round $surface-lighten-1;
        padding: 1 2;
        width: 1fr;
        min-height: 18;
    }
    .welcome-card.-primary {
        border: round $primary;
    }
    .welcome-card-title {
        text-style: bold;
        margin-bottom: 1;
    }
    .welcome-card-copy {
        color: $text-muted;
        margin-bottom: 1;
    }
    #new-run-input {
        margin: 1 0;
    }
    #new-run-actions {
        height: auto;
        margin-top: 1;
    }
    #btn-new-run {
        min-width: 18;
    }
    """

    def compose(self) -> ComposeResult:
        runs = self.app.persistence.list_runs()

        with Center():
            with Vertical(id="welcome-shell"):
                with Vertical(id="welcome-hero"):
                    yield Static("APTAMER WORKFLOW", id="welcome-kicker")
                    yield Static("Aptgent", id="welcome-title")
                    yield Static(
                        "Keyboard-first aptamer design workflow. Start a fresh run here, then use /resume in chat to reopen a saved state.",
                        id="welcome-subtitle",
                    )
                with Vertical(id="welcome-body", classes="welcome-card -primary"):
                    yield Static("New Run", classes="welcome-card-title")
                    yield Static(
                        "Create a new workflow ID now, or leave it blank and let Aptgent generate one.",
                        classes="welcome-card-copy",
                    )
                    if runs:
                        count = len(runs)
                        noun = "run" if count == 1 else "runs"
                        yield Static(
                            f"[dim]{count} saved {noun} available. Open chat and type /resume to switch.[/]",
                            classes="welcome-card-copy",
                        )
                    yield Input(placeholder="Run name (optional)", id="new-run-input")
                    with Horizontal(id="new-run-actions"):
                        yield Button("Create New Run", id="btn-new-run", variant="primary")
                yield Footer()

    def on_mount(self) -> None:
        self.call_after_refresh(self._focus_default)

    def _focus_default(self) -> None:
        try:
            self.query_one("#new-run-input", Input).focus()
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-new-run":
            self._create_new_run()

    def action_new_run(self) -> None:
        self._create_new_run()

    def action_quit(self) -> None:
        self.app.exit()

    def _create_new_run(self) -> None:
        try:
            name = self.query_one("#new-run-input", Input).value.strip()
        except Exception:
            name = ""
        run_id = name if name else None
        state = self.app.engine.create_run(run_id)
        self.app.set_run_id(state.run_id)
        self.app.push_screen("chat")
