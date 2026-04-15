from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Button, Input, OptionList, Static
from textual.widgets.option_list import Option

from aptgent.domain.enums import Step
from aptgent.tui.commands import DEFAULT_SLASH_COMMANDS, SlashCommand


class _BaseBubble(Static):
    """Shared styling for chat bubbles."""

    DEFAULT_CSS = """
    _BaseBubble {
        background: $surface-darken-1;
        padding: 1 2;
        margin: 0 4 1 0;
        width: 95%;
        border-left: wide $surface-lighten-1;
    }
    """


class SystemBubble(_BaseBubble):
    """A system message bubble in the chat log."""

    DEFAULT_CSS = """
    SystemBubble {
        background: $surface-darken-1;
        padding: 1 2;
        margin: 0 4 1 0;
        width: 95%;
        border-left: wide $surface-lighten-1;
    }
    """

    def __init__(self, text: str, **kwargs) -> None:
        super().__init__(text, **kwargs)


class StreamingBubble(Static):
    """A system message bubble that supports typewriter/streaming effect."""

    DEFAULT_CSS = """
    StreamingBubble {
        background: $surface-darken-1;
        padding: 1 2;
        margin: 0 4 1 0;
        width: 95%;
        border-left: wide $surface-lighten-1;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__("▌", **kwargs)
        self._buffer = ""

    def append_text(self, text: str) -> None:
        self._buffer += text
        self.update(self._buffer + "▌")
        try:
            self.scroll_visible(animate=False)
        except Exception:
            pass

    def finalize(self) -> None:
        self.update(self._buffer)


class UserBubble(Static):
    """A user message bubble in the chat log."""

    DEFAULT_CSS = """
    UserBubble {
        background: $primary-darken-2;
        color: $text;
        padding: 1 2;
        margin: 0 0 1 4;
        width: 80%;
        text-align: right;
        border-right: wide $primary-lighten-1;
    }
    """

    def __init__(self, text: str, **kwargs) -> None:
        super().__init__(text, **kwargs)


class ProgressBubble(Static):
    """A progress bar widget for the chat log."""

    DEFAULT_CSS = """
    ProgressBubble {
        background: $surface-darken-1;
        padding: 1 2;
        margin: 0 4 1 0;
        width: 95%;
        border-left: wide $primary;
    }
    """

    def __init__(self, total: int, label: str = "Progress", **kwargs) -> None:
        super().__init__("", **kwargs)
        self._total = total
        self._current = 0
        self._label = label
        self._info = ""
        self._update_display()

    def set_progress(self, current: int, info: str = "") -> None:
        self._current = min(current, self._total)
        if info:
            self._info = info
        self._update_display()
        try:
            self.scroll_visible(animate=False)
        except Exception:
            pass

    def finish(self, message: str) -> None:
        self.update(f"[bold green]✓[/bold green] {message}")

    def _update_display(self) -> None:
        if self._total <= 0:
            self.update(f"{self._label}…")
            return
        pct = self._current / self._total * 100
        bar_width = 30
        filled = int(bar_width * self._current / self._total)
        bar = "█" * filled + "░" * (bar_width - filled)
        text = (
            f"{self._label}\n"
            f"[bold cyan]{bar}[/bold cyan] {pct:.1f}%  ({self._current:,}/{self._total:,})"
        )
        if self._info:
            text += f"\n{self._info}"
        self.update(text)


class StepDivider(Static):
    """Visual separator between workflow steps."""

    DEFAULT_CSS = """
    StepDivider {
        color: $primary-lighten-1;
        text-style: bold;
        background: $surface-darken-2;
        padding: 0 1;
        margin: 1 0;
    }
    """

    def __init__(self, step: Step, **kwargs) -> None:
        name = step.value.replace("_", " ").title()
        super().__init__(f"─── {name} ───", **kwargs)
        self.step = step


class ActivityBubble(Static):
    """A breathing status bubble that stays at the end of the chat log."""

    _FRAMES = [
        "[#6b7280]✳[/]",
        "[#9ca3af]✳[/]",
        "[bold #facc15]✳[/]",
        "[#9ca3af]✳[/]",
    ]

    DEFAULT_CSS = """
    ActivityBubble {
        background: $surface-darken-1;
        border-left: wide $warning;
        padding: 1 2;
        margin: 0 4 1 0;
        width: 95%;
        height: auto;
    }
    """

    def __init__(self, text: str = "", **kwargs) -> None:
        super().__init__("", **kwargs)
        self._frame_idx = 0
        self._timer = None
        self._text = text

    def on_mount(self) -> None:
        self._tick()
        self._timer = self.set_interval(0.3, self._tick)

    def on_unmount(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    def set_text(self, text: str) -> None:
        self._text = text
        self._update_render()

    def finalize(self, text: str | None = None) -> None:
        if text is not None:
            self._text = text
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        self.update(f"[bold #facc15]•[/] {self._text}")

    def _tick(self) -> None:
        self._update_render()
        self._frame_idx += 1
        try:
            self.scroll_visible(animate=False)
        except Exception:
            pass

    def _update_render(self) -> None:
        frame = self._FRAMES[self._frame_idx % len(self._FRAMES)]
        self.update(f"{frame} {self._text}")


class InputBar(Vertical):
    """Bottom input bar with text field and send button."""

    class Submitted(Message):
        """Posted when the user submits text."""

        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

    DEFAULT_CSS = """
    InputBar {
        height: auto;
        dock: bottom;
        padding: 0 1 1 1;
        background: $surface-darken-2;
        border-top: tall $surface-lighten-1;
    }
    #command-list {
        height: auto;
        max-height: 7;
        margin: 0 0 1 0;
        border: tall $surface-lighten-1;
        background: $surface-darken-1;
        display: none;
    }
    InputBar.-commands-visible #command-list {
        display: block;
    }
    #input-row {
        height: 3;
    }
    #input-row > Input {
        width: 1fr;
    }
    #input-row > Button {
        margin-left: 1;
    }
    InputBar.-disabled {
        background: $surface;
    }
    """

    def __init__(
        self,
        *,
        commands: tuple[SlashCommand, ...] = DEFAULT_SLASH_COMMANDS,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._enabled = True
        self._commands = commands
        self._filtered_commands: tuple[SlashCommand, ...] = ()

    def compose(self) -> ComposeResult:
        yield OptionList(id="command-list")
        with Horizontal(id="input-row"):
            yield Input(placeholder="Type a message...", id="chat-input")
            yield Button("Send", id="btn-send", variant="primary")

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        if not enabled:
            self.close_command_palette()
        try:
            inp = self.query_one("#chat-input", Input)
            btn = self.query_one("#btn-send", Button)
            inp.disabled = not enabled
            btn.disabled = not enabled
        except Exception:
            pass
        self.set_class(not enabled, "-disabled")

    def set_placeholder(self, text: str) -> None:
        try:
            self.query_one("#chat-input", Input).placeholder = text
        except Exception:
            pass

    def clear_input(self) -> None:
        try:
            self.query_one("#chat-input", Input).value = ""
        except Exception:
            pass

    def command_palette_open(self) -> bool:
        return self.has_class("-commands-visible")

    def close_command_palette(self) -> None:
        self._filtered_commands = ()
        self.set_class(False, "-commands-visible")
        try:
            option_list = self.query_one("#command-list", OptionList)
            option_list.clear_options()
        except Exception:
            pass

    def _submit(self) -> None:
        if not self._enabled:
            return
        try:
            inp = self.query_one("#chat-input", Input)
        except Exception:
            return
        text = inp.value.strip()
        if not text:
            return
        if self.command_palette_open() and text.startswith("/") and self._filtered_commands:
            self._submit_command(self._filtered_commands[0].name)
            return
        self.close_command_palette()
        if text:
            self.post_message(self.Submitted(text))
            self.clear_input()

    def _submit_command(self, command_name: str) -> None:
        self.close_command_palette()
        self.post_message(self.Submitted(command_name))
        self.clear_input()

    def _update_command_palette(self, text: str) -> None:
        command_token, sep, _rest = text.partition(" ")
        if not command_token.startswith("/") or sep:
            self.close_command_palette()
            return

        query = command_token[1:].strip().lower()
        matches = tuple(
            command
            for command in self._commands
            if not query or command.name[1:].startswith(query)
        )
        self._filtered_commands = matches
        if not matches:
            self.close_command_palette()
            return

        options = [
            Option(
                f"[bold]{command.name}[/bold]\n[dim]{command.description}[/dim]",
                id=command.name,
            )
            for command in matches
        ]
        option_list = self.query_one("#command-list", OptionList)
        option_list.clear_options()
        option_list.add_options(options)
        option_list.highlighted = 0
        self.set_class(True, "-commands-visible")

    def on_input_changed(self, event: Input.Changed) -> None:
        self._update_command_palette(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-send":
            event.stop()
            self._submit()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id != "command-list":
            return
        event.stop()
        command_name = event.option.id
        if command_name:
            self._submit_command(command_name)

    def on_key(self, event) -> None:
        if not self.command_palette_open():
            return
        try:
            option_list = self.query_one("#command-list", OptionList)
        except Exception:
            return

        if event.key == "down":
            event.stop()
            option_list.action_cursor_down()
        elif event.key == "up":
            event.stop()
            option_list.action_cursor_up()
        elif event.key == "enter":
            event.stop()
            if option_list.highlighted is not None:
                option_list.action_select()
        elif event.key == "escape":
            event.stop()
            self.close_command_palette()
