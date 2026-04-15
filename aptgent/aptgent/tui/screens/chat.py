from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Static

from aptgent.domain.enums import Step
from aptgent.tui.widgets.chat_widgets import InputBar, StepDivider, SystemBubble, UserBubble
from aptgent.tui.widgets.step_handlers import StepHandler, create_handler
from aptgent.tui.widgets.structured_input import StructuredActionRequested, StructuredInputSubmitted


class ChatScreen(Screen):
    """Single screen that hosts the entire workflow as a chat conversation."""

    CSS = """
    #chat-log {
        height: 1fr;
        padding: 0 1;
        scrollbar-size: 1 1;
    }
    .system-bubble {
        background: $surface-darken-1;
        padding: 1 2;
        margin: 0 4 1 0;
        width: 95%;
    }
    .user-bubble {
        background: $primary-darken-2;
        color: $text;
        padding: 1 2;
        margin: 0 0 1 4;
        width: 80%;
        text-align: right;
    }
    .step-divider {
        color: $primary-lighten-1;
        text-style: bold;
        padding: 0 1;
        margin: 1 0;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._handler: StepHandler | None = None

    def compose(self) -> ComposeResult:
        yield self.app.progress_bar
        yield self.app.status_panel
        yield VerticalScroll(id="chat-log")
        yield InputBar(id="input-bar")

    def on_mount(self) -> None:
        state = self.app.current_state
        step = state.current_step
        self._start_step(step)

    # -- Public API for step handlers --

    def add_system_message(self, text: str, extra_class: str = "") -> None:
        """Append a system bubble to the chat log."""
        chat_log = self.query_one("#chat-log", VerticalScroll)
        classes = "system-bubble"
        if extra_class:
            classes += f" {extra_class}"
        bubble = SystemBubble(text)
        bubble.add_class(*[c for c in classes.split() if c != "system-bubble"])
        chat_log.mount(bubble)
        chat_log.scroll_end(animate=False)

    def add_streaming_message(self) -> "StreamingBubble":
        """Append a streaming bubble to the chat log and return it."""
        from aptgent.tui.widgets.chat_widgets import StreamingBubble
        chat_log = self.query_one("#chat-log", VerticalScroll)
        bubble = StreamingBubble()
        chat_log.mount(bubble)
        chat_log.scroll_end(animate=False)
        return bubble

    def add_user_message(self, text: str) -> None:
        """Append a user bubble to the chat log."""
        chat_log = self.query_one("#chat-log", VerticalScroll)
        chat_log.mount(UserBubble(text))
        chat_log.scroll_end(animate=False)

    def add_structured_widget(self, widget) -> None:
        """Mount a structured input widget into the chat log."""
        chat_log = self.query_one("#chat-log", VerticalScroll)
        chat_log.mount(widget)
        chat_log.scroll_end(animate=False)

    def set_input_enabled(self, enabled: bool) -> None:
        try:
            self.query_one("#input-bar", InputBar).set_enabled(enabled)
        except Exception:
            pass

    def set_input_placeholder(self, text: str) -> None:
        try:
            self.query_one("#input-bar", InputBar).set_placeholder(text)
        except Exception:
            pass

    def advance_to_step(self, step: Step) -> None:
        """Transition to the next step in the chat."""
        state = self.app.current_state
        if step != state.current_step:
            self.app.engine.transition_to(state, step)
        self.app.progress_bar.set_step(step)
        self.app.save_state()
        self._start_step(step)

    # -- Internal --

    def _start_step(self, step: Step) -> None:
        """Add a step divider and create the handler for this step."""
        self.query_one("#chat-log", VerticalScroll).mount(StepDivider(step))
        self.query_one("#chat-log", VerticalScroll).scroll_end(animate=False)
        self._handler = create_handler(step, self)
        self._handler.enter()

    # -- Event handlers --

    def on_input_bar_submitted(self, event: InputBar.Submitted) -> None:
        """Handle user text input from the bottom input bar."""
        event.stop()
        if not self._handler:
            return
        text = event.value.strip()
        if not text:
            return
        self.add_user_message(text)
        self.app.current_state.input_payload["user_text"] = text
        self._handler.handle_user_input(text)

    def on_structured_input_submitted(self, event: StructuredInputSubmitted) -> None:
        """Handle structured panel submissions."""
        event.stop()
        if self._handler:
            self._handler.handle_structured_input(event.data)

    def on_structured_action_requested(self, event: StructuredActionRequested) -> None:
        """Handle structured panel action requests."""
        event.stop()
        if self._handler:
            self._handler.handle_action(event.action)
