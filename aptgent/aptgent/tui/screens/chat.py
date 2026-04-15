from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen

from aptgent.domain.enums import Step
from aptgent.tui.widgets.chat_widgets import InputBar, StepDivider, StreamingBubble, SystemBubble, ThinkingBubble, UserBubble
from aptgent.tui.widgets.step_handlers import StepHandler, create_handler
from aptgent.tui.widgets.structured_input import StructuredActionRequested, StructuredInputSubmitted


class ChatScreen(Screen):
    """Single screen that hosts the entire workflow as a chat conversation."""

    BINDINGS = [
        Binding("escape", "focus_input", "Focus Input", show=False),
    ]

    CSS = """
    #chat-log {
        height: 1fr;
        padding: 0 1;
        scrollbar-size: 1 1;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._handler: StepHandler | None = None
        self._thinking_bubble: ThinkingBubble | None = None

    def compose(self) -> ComposeResult:
        yield self.app.progress_bar
        yield self.app.status_panel
        yield VerticalScroll(id="chat-log")
        yield InputBar(id="input-bar")

    def on_mount(self) -> None:
        state = self.app.current_state
        step = state.current_step
        self._start_step(step)
        self.set_timer(0.1, self._focus_input)

    # -- Public API for step handlers --

    def add_system_message(self, text: str, extra_class: str = "") -> None:
        """Append a system bubble to the chat log."""
        chat_log = self.query_one("#chat-log", VerticalScroll)
        bubble = SystemBubble(text)
        if extra_class:
            bubble.add_class(extra_class)
        chat_log.mount(bubble)
        chat_log.scroll_end(animate=False)

    def add_streaming_message(self) -> StreamingBubble:
        """Append a streaming bubble to the chat log and return it."""
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
        if enabled:
            self._remove_thinking()
        else:
            self._show_thinking()

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
        chat_log = self.query_one("#chat-log", VerticalScroll)
        chat_log.mount(StepDivider(step))
        chat_log.scroll_end(animate=False)
        self._handler = create_handler(step, self)
        self._handler.enter()

    def _show_thinking(self) -> None:
        if self._thinking_bubble is None:
            bubble = ThinkingBubble()
            self._thinking_bubble = bubble
            chat_log = self.query_one("#chat-log", VerticalScroll)
            chat_log.mount(bubble)
            chat_log.scroll_end(animate=False)

    def _remove_thinking(self) -> None:
        if self._thinking_bubble is not None:
            try:
                self._thinking_bubble.remove()
            except Exception:
                pass
            self._thinking_bubble = None

    def _focus_input(self) -> None:
        try:
            self.query_one("#chat-input").focus()
        except Exception:
            pass

    def action_focus_input(self) -> None:
        self._focus_input()

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
