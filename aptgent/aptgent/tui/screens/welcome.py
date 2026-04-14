from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Input, Label, ListItem, ListView, Static


class WelcomeScreen(Screen):
    """Entry screen: create new run or resume existing."""

    def compose(self) -> ComposeResult:
        yield Static("Aptgent — Aptamer Design Assistant", classes="title")
        yield Static("Select an existing run to resume, or create a new one.", classes="info-text")

        with Horizontal():
            with Vertical():
                yield Static("Existing Runs:", classes="title")
                runs = self.app.persistence.list_runs()
                if runs:
                    items = [ListItem(Label(r)) for r in runs]
                    yield ListView(*items, id="run-list")
                else:
                    yield Static("No existing runs found.", classes="info-text")

            with Vertical():
                yield Static("New Run:", classes="title")
                yield Input(placeholder="Optional run name", id="new-run-input")
                yield Button("Create New Run", id="btn-new-run", variant="primary")

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        label = event.item.query_one(Label)
        run_id = str(label.content)
        self.app.set_run_id(run_id)
        self.app.push_screen("chat")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-new-run":
            name = self.query_one("#new-run-input", Input).value.strip()
            run_id = name if name else None
            state = self.app.engine.create_run(run_id)
            self.app.set_run_id(state.run_id)
            self.app.push_screen("chat")
