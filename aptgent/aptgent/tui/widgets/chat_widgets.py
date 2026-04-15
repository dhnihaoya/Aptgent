from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Button, Input, Static

from aptgent.domain.enums import Step


class SystemBubble(Static):
    """A system message bubble in the chat log."""

    DEFAULT_CSS = """
    SystemBubble {
        background: $surface-darken-1;
        padding: 1 2;
        margin: 0 4 1 0;
        width: 95%;
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
        padding: 0 1;
        margin: 1 0;
    }
    """

    def __init__(self, step: Step, **kwargs) -> None:
        name = step.value.replace("_", " ").title()
        super().__init__(f"─── {name} ───", **kwargs)
        self.step = step


class ThinkingBubble(Static):
    """A breathing indicator shown while the system is working."""

    _FRAMES = [
        "[#555555]✳[/]",
        "[#776600]✳[/]",
        "[#aa9900]✳[/]",
        "[bold #ddcc00]✳[/]",
        "[#aa9900]✳[/]",
        "[#776600]✳[/]",
    ]

    DEFAULT_CSS = """
    ThinkingBubble {
        color: $primary-lighten-1;
        text-style: bold;
        padding: 0 1;
        margin: 0 4 1 0;
        width: auto;
        height: auto;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__("", **kwargs)
        self._frame_idx = 0
        self._timer = None

    def on_mount(self) -> None:
        self._tick()
        self._timer = self.set_interval(0.3, self._tick)

    def on_unmount(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    def _tick(self) -> None:
        self.update(self._FRAMES[self._frame_idx % len(self._FRAMES)])
        self._frame_idx += 1
        try:
            self.scroll_visible(animate=False)
        except Exception:
            pass


class InputBar(Horizontal):
    """Bottom input bar with text field and send button."""

    class Submitted(Message):
        """Posted when the user submits text."""

        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

    DEFAULT_CSS = """
    InputBar {
        height: 3;
        dock: bottom;
        padding: 0 1;
        background: $surface-darken-2;
    }
    InputBar > Input {
        width: 1fr;
    }
    InputBar > Button {
        margin-left: 1;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._enabled = True

    def compose(self) -> ComposeResult:
        yield Input(placeholder="Type a message...", id="chat-input")
        yield Button("Send", id="btn-send", variant="primary")

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        try:
            inp = self.query_one("#chat-input", Input)
            btn = self.query_one("#btn-send", Button)
            inp.disabled = not enabled
            btn.disabled = not enabled
        except Exception:
            pass

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

    def _submit(self) -> None:
        if not self._enabled:
            return
        try:
            inp = self.query_one("#chat-input", Input)
        except Exception:
            return
        text = inp.value.strip()
        if text:
            self.post_message(self.Submitted(text))
            self.clear_input()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-send":
            event.stop()
            self._submit()
