from __future__ import annotations

import logging
import math
import re

from rich.markdown import Markdown
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.message import Message
from textual.widgets import Button, OptionList, Static, TextArea
from textual.widgets.option_list import Option

from aptgent.domain.enums import Step
from aptgent.tui.commands import DEFAULT_SLASH_COMMANDS, SlashCommand

_log = logging.getLogger(__name__)

_BREATH_INTERVAL_SECONDS = 0.42
_DEFAULT_THEME_VARIABLES = {
    "chat-thinking-label": "#a9bad1",
    "chat-thinking-frame-muted": "#718198",
    "chat-thinking-frame-soft": "#9baabd",
    "chat-thinking-frame-bright": "#d7e2ee",
    "chat-thinking-frame-hot": "#f1c15b",
    "chat-activity-label": "#a9bad1",
    "chat-activity-frame-muted": "#5f6b7a",
    "chat-activity-frame-soft": "#8795a7",
    "chat-activity-frame-bright": "#d7deea",
    "chat-activity-frame-hot": "#f1c15b",
    "chat-activity-final-icon": "#f1c15b",
}


def _theme_variable(widget: Static, name: str) -> str:
    try:
        return widget.app.current_theme.variables.get(
            name,
            widget.app.get_theme_variable_defaults().get(name, _DEFAULT_THEME_VARIABLES[name]),
        )
    except Exception:
        return _DEFAULT_THEME_VARIABLES[name]


def _breathing_frames(
    widget: Static,
    *,
    muted_name: str,
    soft_name: str,
    bright_name: str,
    hot_name: str,
) -> list[tuple[str, bool, str]]:
    muted = _theme_variable(widget, muted_name)
    soft = _theme_variable(widget, soft_name)
    bright = _theme_variable(widget, bright_name)
    hot = _theme_variable(widget, hot_name)
    return [
        (muted, False, "·"),
        (soft, False, "•"),
        (bright, False, "•"),
        (hot, True, "✦"),
        (bright, False, "•"),
        (soft, False, "•"),
    ]


def _normalize_markdown_for_chat(text: str) -> str:
    normalized_lines: list[str] = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if not stripped.startswith("#"):
            normalized_lines.append(line)
            continue
        heading = stripped.lstrip("#").strip()
        if heading:
            normalized_lines.append(f"**{heading}**")
        else:
            normalized_lines.append(line)
    return "\n".join(normalized_lines)


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

    def __init__(self, text: str = "", *, markdown: bool = False, **kwargs) -> None:
        super().__init__("", **kwargs)
        self._markdown = markdown
        self._text = ""
        self.set_content(text)

    def set_content(self, text: str) -> None:
        self._text = text
        if self._markdown:
            super().update(Markdown(_normalize_markdown_for_chat(text or " ")))
        else:
            super().update(text)


class SystemBubble(_BaseBubble):
    """A system message bubble in the chat log."""

    DEFAULT_CSS = """
    SystemBubble {
        background: $chat-system-background;
        color: $chat-system-foreground;
        padding: 1 2;
        margin: 0 4 1 0;
        width: 84%;
        border-left: wide $chat-system-accent;
    }
    """

    def __init__(self, text: str, *, markdown: bool = False, **kwargs) -> None:
        super().__init__(text, markdown=markdown, **kwargs)


class StreamingBubble(Static):
    """A system message bubble that supports typewriter/streaming effect."""

    DEFAULT_CSS = """
    StreamingBubble {
        background: $chat-stream-background;
        color: $chat-stream-foreground;
        padding: 1 2;
        margin: 0 4 1 0;
        width: 84%;
        border-left: wide $chat-stream-accent;
    }
    """

    def __init__(self, *, markdown: bool = False, **kwargs) -> None:
        super().__init__("", **kwargs)
        self._buffer = ""
        self._markdown = markdown
        self.update("▌")

    def append_text(self, text: str) -> None:
        self._buffer += text
        self.update(Text(self._buffer + "▌"))

    def finalize(self) -> None:
        if self._markdown:
            self.update(Markdown(_normalize_markdown_for_chat(self._buffer or " ")))
        else:
            self.update(self._buffer)


class ThinkingBubble(Static):
    """A collapsible bubble for model reasoning content."""

    DEFAULT_CSS = """
    ThinkingBubble {
        background: $chat-thinking-background;
        color: $chat-thinking-foreground;
        padding: 1 2;
        margin: 0 4 1 0;
        width: 84%;
        border-left: wide $chat-thinking-accent;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__("", **kwargs)
        self._buffer = ""
        self._expanded = False
        self._streaming = True
        self._frame_idx = 0
        self._timer = None
        self._refresh_display()

    @property
    def has_content(self) -> bool:
        return bool(self._buffer.strip())

    @property
    def expanded(self) -> bool:
        return self._expanded

    @property
    def estimated_tokens(self) -> int:
        parts = re.findall(r"[A-Za-z0-9_]+|[^\x00-\x7F]|\S", self._buffer)
        return len(parts)

    def on_mount(self) -> None:
        self._tick()
        self._timer = self.set_interval(_BREATH_INTERVAL_SECONDS, self._tick)

    def on_unmount(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    def append_text(self, text: str) -> None:
        self._buffer += text
        self._refresh_display()

    def toggle(self) -> None:
        if not self.has_content:
            return
        self._expanded = not self._expanded
        self._refresh_display()

    def finalize(self) -> None:
        self._streaming = False
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        self._refresh_display()

    def _tick(self) -> None:
        self._refresh_display()
        self._frame_idx += 1

    def _header_style(self) -> str:
        if not self._streaming:
            return f"bold {_theme_variable(self, 'chat-thinking-frame-hot')}", "✦"
        frames = _breathing_frames(
            self,
            muted_name="chat-thinking-frame-muted",
            soft_name="chat-thinking-frame-soft",
            bright_name="chat-thinking-frame-bright",
            hot_name="chat-thinking-frame-hot",
        )
        color, bold, icon = frames[self._frame_idx % len(frames)]
        return (f"bold {color}" if bold else color), icon

    def _refresh_display(self) -> None:
        arrow = "▲" if self._expanded else "▼"
        style, icon = self._header_style()
        action_label = "collapse" if self._expanded else "expand"
        label_color = _theme_variable(self, "chat-thinking-label")
        header_markup = (
            f"[{style}]{icon}[/] [bold {label_color}]Thinking[/] "
            f"[dim]{self.estimated_tokens} tokens {arrow} (ctrl+o to {action_label})[/dim]"
        )
        if not self._expanded:
            self.update(header_markup)
            return

        header = Text.from_markup(header_markup)
        body = Text(self._buffer)
        if self._streaming:
            body.append("▌")
        self.update(Text("\n").join([header, body]))


class UserBubble(Static):
    """A user message bubble in the chat log."""

    DEFAULT_CSS = """
    UserBubble {
        background: $chat-user-background;
        color: $chat-user-foreground;
        padding: 1 2;
        margin: 0 0 1 18;
        width: 72%;
        text-align: right;
        border-right: wide $chat-user-accent;
    }
    """

    def __init__(self, text: str, **kwargs) -> None:
        super().__init__(text, **kwargs)


class ProgressBubble(Static):
    """A progress bar widget for the chat log."""

    DEFAULT_CSS = """
    ProgressBubble {
        background: $chat-stream-background;
        color: $chat-stream-foreground;
        padding: 1 2;
        margin: 0 4 1 0;
        width: 84%;
        border-left: wide $chat-stream-accent;
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
        color: $chat-divider-color;
        text-style: bold;
        background: transparent;
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

    DEFAULT_CSS = """
    ActivityBubble {
        background: $chat-activity-background;
        color: $chat-activity-foreground;
        border-left: wide $chat-activity-accent;
        padding: 1 2;
        margin: 0 4 1 0;
        width: 84%;
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
        self._timer = self.set_interval(_BREATH_INTERVAL_SECONDS, self._tick)

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
        label = _theme_variable(self, "chat-activity-label")
        icon = _theme_variable(self, "chat-activity-final-icon")
        self.update(f"[bold {label}]run[/] [bold {icon}]•[/] {self._text}")

    def _tick(self) -> None:
        self._update_render()
        self._frame_idx += 1

    def _update_render(self) -> None:
        frames = _breathing_frames(
            self,
            muted_name="chat-activity-frame-muted",
            soft_name="chat-activity-frame-soft",
            bright_name="chat-activity-frame-bright",
            hot_name="chat-activity-frame-hot",
        )
        color, bold, icon = frames[self._frame_idx % len(frames)]
        style = f"bold {color}" if bold else color
        label = _theme_variable(self, "chat-activity-label")
        self.update(f"[bold {label}]run[/] [{style}]{icon} {self._text}[/]")


class ChatInput(TextArea):
    """Prompt-style text area with an Input-compatible value alias."""

    BINDINGS = [
        Binding("enter", "submit", show=False, priority=True),
    ]

    class Submitted(Message):
        """Posted when Enter should submit the prompt."""

    @property
    def value(self) -> str:
        return self.text

    @value.setter
    def value(self, text: str) -> None:
        self.load_text(text)

    def action_submit(self) -> None:
        self.post_message(self.Submitted())


class InputBar(Vertical):
    """Bottom input bar with text field and send button."""

    MIN_INPUT_HEIGHT = 3
    MAX_INPUT_HEIGHT = 8

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
        height: auto;
    }
    #input-row > TextArea {
        width: 1fr;
        height: 3;
    }
    #input-row > Button {
        margin-left: 1;
        height: 3;
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
        self._allow_empty = False
        self._commands = commands
        self._filtered_commands: tuple[SlashCommand, ...] = ()
        self._input_height = self.MIN_INPUT_HEIGHT

    @property
    def input_height(self) -> int:
        return self._input_height

    def compose(self) -> ComposeResult:
        yield OptionList(id="command-list")
        with Horizontal(id="input-row"):
            yield ChatInput(placeholder="Type a message...", id="chat-input", compact=True)
            yield Button("Send", id="btn-send", variant="primary")

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        if not enabled:
            self.close_command_palette()
        try:
            inp = self.query_one("#chat-input", ChatInput)
            btn = self.query_one("#btn-send", Button)
            inp.disabled = not enabled
            btn.disabled = not enabled
        except NoMatches:
            _log.debug("InputBar widgets not yet mounted", exc_info=True)
        self.set_class(not enabled, "-disabled")

    def set_placeholder(self, text: str) -> None:
        try:
            self.query_one("#chat-input", ChatInput).placeholder = text
        except NoMatches:
            _log.debug("chat-input not yet mounted", exc_info=True)

    def set_commands(self, commands: tuple[SlashCommand, ...]) -> None:
        self._commands = commands
        try:
            current_value = self.query_one("#chat-input", ChatInput).value
        except NoMatches:
            current_value = ""
        self._update_command_palette(current_value)

    def clear_input(self) -> None:
        try:
            self.query_one("#chat-input", ChatInput).value = ""
            self._resize_input("")
        except NoMatches:
            _log.debug("chat-input not yet mounted", exc_info=True)

    def command_palette_open(self) -> bool:
        return self.has_class("-commands-visible")

    def close_command_palette(self) -> None:
        self._filtered_commands = ()
        self.set_class(False, "-commands-visible")
        try:
            option_list = self.query_one("#command-list", OptionList)
            option_list.clear_options()
        except NoMatches:
            _log.debug("command-list not mounted", exc_info=True)

    def _submit(self) -> None:
        if not self._enabled:
            return
        try:
            inp = self.query_one("#chat-input", ChatInput)
        except Exception:
            return
        text = inp.value.strip()
        if not text:
            if self._allow_empty:
                self.post_message(self.Submitted(""))
                self.clear_input()
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

    def _resize_input(self, text: str) -> None:
        try:
            inp = self.query_one("#chat-input", ChatInput)
            row = self.query_one("#input-row", Horizontal)
            button = self.query_one("#btn-send", Button)
        except NoMatches:
            return

        wrap_width = max(1, (inp.content_size.width or inp.size.width or 20) - 2)
        visual_lines = 0
        for line in text.splitlines() or [""]:
            visual_lines += max(1, math.ceil(len(line) / wrap_width))
        height = min(self.MAX_INPUT_HEIGHT, max(self.MIN_INPUT_HEIGHT, visual_lines + 2))

        self._input_height = height
        inp.styles.height = height
        row.styles.height = height
        button.styles.height = height

    def on_mount(self) -> None:
        self._resize_input("")

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id != "chat-input":
            return
        self._update_command_palette(event.text_area.text)
        self._resize_input(event.text_area.text)

    def on_chat_input_submitted(self, event: ChatInput.Submitted) -> None:
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
        if event.key == "enter":
            event.stop()
            if self.command_palette_open():
                try:
                    option_list = self.query_one("#command-list", OptionList)
                except Exception:
                    return
                if option_list.highlighted is not None:
                    option_list.action_select()
                return
            self._submit()
            return

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
        elif event.key == "escape":
            event.stop()
            self.close_command_palette()
