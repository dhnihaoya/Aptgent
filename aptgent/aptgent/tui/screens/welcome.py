from __future__ import annotations

import logging

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import Screen
from textual.widgets import Static

from aptgent.tui.commands import DEFAULT_SLASH_COMMANDS

_log = logging.getLogger(__name__)
from aptgent.tui.screens.theme_picker import ThemePickerScreen
from aptgent.tui.screens.resume import ResumePickerScreen
from aptgent.tui.steps.common import (
    INITIAL_INTAKE_PLACEHOLDER,
    format_initial_intake_prompt,
)
from aptgent.tui.widgets.chat_widgets import InputBar, StepDivider, SystemBubble


class WelcomeScreen(Screen):
    """Chat-first landing screen before a run exists."""

    LOGO = "\n".join(
        [
            " /\\/\\ ",
            " \\\\// ",
            " //\\\\ ",
            " \\\\// ",
            " /\\/\\ ",
        ]
    )

    WORDMARK = "\n".join(
        [
            " ███   ████   █████   ████  █████  █   █  █████",
            "█   █  █   █    █    █      █      ██  █    █  ",
            "█████  ████     █    █  ██  ███    █ █ █    █  ",
            "█   █  █        █    █   █  █      █  ██    █  ",
            "█   █  █        █     ███   █████  █   █    █  ",
        ]
    )

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
        background: $panel;
        border: round $primary;
        padding: 1 3 1 3;
        margin: 1 1 0 1;
        height: auto;
    }
    #welcome-status {
        height: auto;
        margin-bottom: 1;
        padding-bottom: 1;
        border-bottom: tall $secondary;
    }
    #welcome-status-label {
        width: 1fr;
        color: $text-muted;
    }
    #welcome-status-state {
        width: auto;
        color: $success;
        text-style: bold;
    }
    #welcome-brand {
        height: auto;
        margin-top: 1;
    }
    #welcome-logo {
        width: 10;
        color: $primary;
        background: $background 12%;
        border: round $primary 30%;
        padding: 1 1;
        margin-right: 3;
        content-align: center middle;
    }
    #welcome-wordmark {
        color: $primary-lighten-2;
        text-style: bold;
    }
    #welcome-copy {
        width: 1fr;
        height: auto;
    }
    #welcome-tagline {
        color: $text;
        margin-top: 1;
    }
    #welcome-subtitle {
        color: $text-muted;
        margin-top: 1;
    }
    #welcome-meta {
        color: $primary-lighten-1;
        margin-top: 1;
        padding-top: 1;
        border-top: tall $secondary;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="welcome-hero"):
            with Horizontal(id="welcome-status"):
                yield Static("Workflow Console", id="welcome-status-label")
                yield Static("\u25cf Ready", id="welcome-status-state")
            with Horizontal(id="welcome-brand"):
                yield Static(self.LOGO, id="welcome-logo")
                with Vertical(id="welcome-copy"):
                    yield Static(self.WORDMARK, id="welcome-wordmark")
                    yield Static(
                        "Aptamer design workflow, kept fast and terminal-native.",
                        id="welcome-tagline",
                    )
                    yield Static(
                        "Describe the task to start a new run. Type / to open commands.",
                        id="welcome-subtitle",
                    )
            yield Static("Sequence  •  Target  •  PDB intake", id="welcome-meta")
        yield VerticalScroll(id="welcome-log")
        yield InputBar(id="input-bar", commands=DEFAULT_SLASH_COMMANDS)

    def on_mount(self) -> None:
        self.call_after_refresh(self._focus_input)
        self._seed_log()

    def _seed_log(self) -> None:
        chat_log = self.query_one("#welcome-log", VerticalScroll)
        chat_log.mount(StepDivider(self.app.progress_bar.current_step))
        chat_log.mount(SystemBubble(format_initial_intake_prompt(), markdown=True))
        chat_log.scroll_end(animate=False)
        self.query_one("#input-bar", InputBar).set_placeholder(INITIAL_INTAKE_PLACEHOLDER)

    def _focus_input(self) -> None:
        try:
            self.query_one("#chat-input").focus()
        except NoMatches:
            _log.debug("chat-input not mounted", exc_info=True)

    def _open_resume_picker(self) -> None:
        if not self.app.persistence.list_runs():
            self.add_system_message("No saved runs available yet.")
            return
        self.app.push_screen(ResumePickerScreen(), self._handle_resume_selection)

    def _open_theme_picker(self) -> None:
        self.app.push_screen(ThemePickerScreen(), self._handle_theme_selection)

    def _handle_resume_selection(self, run_id: str | None) -> None:
        if not run_id:
            self._focus_input()
            return
        self.app.set_run_id(run_id)
        self.app.push_screen("chat")

    def _handle_theme_selection(self, theme_name: str | None) -> None:
        if not theme_name:
            self._focus_input()
            return
        label = self.app.apply_theme(theme_name)
        if label is not None:
            self.add_system_message(f"Theme switched to {label}.")
        self._focus_input()

    def add_system_message(self, text: str, *, markdown: bool = False) -> None:
        chat_log = self.query_one("#welcome-log", VerticalScroll)
        chat_log.mount(SystemBubble(text, markdown=markdown))
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
        if command == "/theme":
            self._open_theme_picker()
            return
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
        if command == "/quit":
            self.app.open_quit_dialog()
            return
        if command.startswith("/"):
            self.add_system_message(f"Unknown command: {command}")
            return
        self.app.start_new_run(initial_message=text)
        self.app.push_screen("chat")
