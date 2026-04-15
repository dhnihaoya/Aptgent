from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Input, Label, ListItem, ListView, Static


class WelcomeScreen(Screen):
    """Entry screen: create new run or resume existing."""

    BINDINGS = [
        Binding("n", "new_run", "New Run"),
        Binding("q", "quit", "Quit"),
    ]

    CSS = """
    WelcomeScreen {
        layout: vertical;
        align: center middle;
    }
    #welcome-hero {
        width: 80;
        height: auto;
        padding: 1 2;
        margin-bottom: 1;
    }
    #welcome-hero > Static {
        text-align: center;
    }
    #welcome-body {
        width: 80;
        height: auto;
        max-height: 24;
    }
    #run-list-pane {
        width: 1fr;
        height: auto;
        max-height: 18;
        padding: 0 1;
    }
    #new-run-pane {
        width: 1fr;
        height: auto;
        padding: 0 1;
    }
    #run-list {
        height: auto;
        max-height: 12;
    }
    #new-run-input {
        margin-bottom: 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Center():
            with Vertical(id="welcome-hero"):
                yield Static(
                    "[bold]🧬 Aptgent[/]\n"
                    "[dim]Aptamer Design Assistant[/]"
                )
        with Horizontal(id="welcome-body"):
            with Vertical(id="run-list-pane"):
                yield Static("[bold]Resume Run[/]")
                runs = self.app.persistence.list_runs()
                if runs:
                    items = [ListItem(Label(r)) for r in runs]
                    yield ListView(*items, id="run-list")
                else:
                    yield Static("[dim]No saved runs.[/]")
            with Vertical(id="new-run-pane"):
                yield Static("[bold]New Run[/]")
                yield Input(placeholder="Run name (optional)", id="new-run-input")
                yield Button("Create New Run", id="btn-new-run", variant="primary")
        yield Footer()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        label = event.item.query_one(Label)
        run_id = str(label.renderable)
        self.app.set_run_id(run_id)
        self.app.push_screen("chat")

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
