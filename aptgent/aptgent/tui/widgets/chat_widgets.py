from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Button, Input, Static

from aptgent.domain.enums import Step


class SystemBubble(Static):
    """A system message bubble in the chat log."""

    def __init__(self, text: str, **kwargs) -> None:
        super().__init__(text, classes="system-bubble", **kwargs)


class StreamingBubble(Static):
    """A system message bubble that supports typewriter/streaming effect."""

    def __init__(self, **kwargs) -> None:
        super().__init__("", classes="system-bubble", **kwargs)
        self._buffer = ""

    def append_text(self, text: str) -> None:
        self._buffer += text
        self.update(self._buffer + "▌")
        # Keep scroll at bottom as text grows
        if self.parent:
            try:
                from textual.containers import VerticalScroll
                vs = self.parent
                if isinstance(vs, VerticalScroll):
                    vs.scroll_end(animate=False)
            except Exception:
                pass

    def finalize(self) -> None:
        self.update(self._buffer)


class UserBubble(Static):
    """A user message bubble in the chat log."""

    def __init__(self, text: str, **kwargs) -> None:
        super().__init__(text, classes="user-bubble", **kwargs)


class StepDivider(Static):
    """Visual separator between workflow steps."""

    def __init__(self, step: Step, **kwargs) -> None:
        name = step.value.replace("_", " ").title()
        super().__init__(f"── {name} ──", classes="step-divider", **kwargs)
        self.step = step


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
        background: $surface-darken-1;
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

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        if not self._enabled:
            return
        text = event.value.strip()
        if text:
            self.post_message(self.Submitted(text))
            self.clear_input()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-send":
            try:
                inp = self.query_one("#chat-input", Input)
                text = inp.value.strip()
                if text and self._enabled:
                    self.post_message(self.Submitted(text))
                    self.clear_input()
            except Exception:
                pass
