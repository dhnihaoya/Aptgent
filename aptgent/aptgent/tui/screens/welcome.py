from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Static

from aptgent.tui.screens.resume import ResumePickerScreen
from aptgent.tui.widgets.chat_widgets import InputBar, StepDivider, SystemBubble


class WelcomeScreen(Screen):
    """Chat-first landing screen before a run exists."""

    BINDINGS = [
        Binding("escape", "request_quit", "Quit", show=False),
    ]

    CSS = """
    #welcome-log {
        height: 1fr;
        padding: 1;
        scrollbar-size: 1 1;
    }
    #welcome-hero {
        background: $surface-darken-2;
        border: round $primary;
        padding: 2 3;
        margin: 1 1 0 1;
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
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="welcome-hero"):
            yield Static("APTAMER WORKFLOW", id="welcome-kicker")
            yield Static("Aptgent", id="welcome-title")
            yield Static(
                "Describe your design task to start a new run. Type / to open commands.",
                id="welcome-subtitle",
            )
        yield VerticalScroll(id="welcome-log")
        yield InputBar(id="input-bar")

    def on_mount(self) -> None:
        self.call_after_refresh(self._focus_input)
        self._seed_log()

    def _seed_log(self) -> None:
        chat_log = self.query_one("#welcome-log", VerticalScroll)
        chat_log.mount(StepDivider(self.app.progress_bar.current_step))
        chat_log.mount(
            SystemBubble(
                "Start with a plain-language brief, sequence, or target molecule. "
                "Use /resume to reopen a saved run."
            )
        )
        chat_log.scroll_end(animate=False)

    def _focus_input(self) -> None:
        try:
            self.query_one("#chat-input").focus()
        except Exception:
            pass

    def _open_resume_picker(self) -> None:
        if not self.app.persistence.list_runs():
            self.add_system_message("No saved runs available yet.")
            return
        self.app.push_screen(ResumePickerScreen(), self._handle_resume_selection)

    def _handle_resume_selection(self, run_id: str | None) -> None:
        if not run_id:
            self._focus_input()
            return
        self.app.set_run_id(run_id)
        self.app.push_screen("chat")

    def add_system_message(self, text: str) -> None:
        chat_log = self.query_one("#welcome-log", VerticalScroll)
        chat_log.mount(SystemBubble(text))
        chat_log.scroll_end(animate=False)

    def action_request_quit(self) -> None:
        input_bar = self.query_one("#input-bar", InputBar)
        if input_bar.command_palette_open():
            input_bar.close_command_palette()
            return
        self.app.open_quit_dialog()

    def on_input_bar_submitted(self, event: InputBar.Submitted) -> None:
        event.stop()
        text = event.value.strip()
        if not text:
            return
        command, _, arg = text.partition(" ")
        if command == "/resume":
            if arg.strip():
                state = self.app.engine.load_run(arg.strip())
                if state is None:
                    self.add_system_message(f"Saved run not found: {arg.strip()}")
                    return
                self.app.set_run_id(state.run_id)
                self.app.push_screen("chat")
                return
            self._open_resume_picker()
            return
        if command.startswith("/"):
            self.add_system_message(f"Unknown command: {command}")
            return
        self.app.start_new_run(initial_message=text)
        self.app.push_screen("chat")
