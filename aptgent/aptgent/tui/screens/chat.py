from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widget import Widget

from aptgent.domain.enums import Step
from aptgent.tui.screens.resume import ResumePickerScreen
from aptgent.tui.widgets.chat_widgets import ActivityBubble, InputBar, StepDivider, StreamingBubble, SystemBubble, UserBubble
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
        self._activity_bubble: ActivityBubble | None = None
        self._active_structured_widget: Widget | None = None

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

    def add_system_message(self, text: str, extra_class: str = "") -> SystemBubble:
        """Append a system bubble to the chat log."""
        chat_log = self.query_one("#chat-log", VerticalScroll)
        bubble = SystemBubble(text)
        if extra_class:
            bubble.add_class(extra_class)
        if self._activity_bubble is not None and self._activity_bubble.is_mounted:
            chat_log.mount(bubble, before=self._activity_bubble)
        else:
            chat_log.mount(bubble)
        chat_log.scroll_end(animate=False)
        return bubble

    def add_streaming_message(self) -> StreamingBubble:
        """Append a streaming bubble to the chat log and return it."""
        chat_log = self.query_one("#chat-log", VerticalScroll)
        bubble = StreamingBubble()
        if self._activity_bubble is not None and self._activity_bubble.is_mounted:
            chat_log.mount(bubble, before=self._activity_bubble)
        else:
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
        self.clear_structured_widget()
        self._active_structured_widget = widget
        if self._activity_bubble is not None and self._activity_bubble.is_mounted:
            chat_log.mount(widget, before=self._activity_bubble)
        else:
            chat_log.mount(widget)
        chat_log.scroll_end(animate=False)
        self.call_after_refresh(lambda: self._focus_widget(widget))

    def clear_structured_widget(self) -> None:
        widget = self._active_structured_widget
        if widget is not None:
            try:
                if widget.is_mounted:
                    widget.remove()
            except Exception:
                pass
        self._active_structured_widget = None

    def show_activity(self, text: str) -> None:
        chat_log = self.query_one("#chat-log", VerticalScroll)
        if self._activity_bubble is None or not self._activity_bubble.is_mounted:
            self._activity_bubble = ActivityBubble(text)
            chat_log.mount(self._activity_bubble)
        else:
            self._activity_bubble.set_text(text)
        chat_log.scroll_end(animate=False)

    def update_activity(self, text: str) -> None:
        if self._activity_bubble is None or not self._activity_bubble.is_mounted:
            self.show_activity(text)
            return
        self._activity_bubble.set_text(text)

    def finish_activity(self, text: str | None = None) -> None:
        if self._activity_bubble is not None and self._activity_bubble.is_mounted:
            self._activity_bubble.finalize(text)

    def clear_activity(self) -> None:
        if self._activity_bubble is not None:
            try:
                if self._activity_bubble.is_mounted:
                    self._activity_bubble.remove()
            except Exception:
                pass
            self._activity_bubble = None

    def set_input_enabled(self, enabled: bool) -> None:
        try:
            self.query_one("#input-bar", InputBar).set_enabled(enabled)
        except Exception:
            pass
        if enabled:
            self.clear_activity()

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
        self.clear_structured_widget()
        self.clear_activity()
        self._start_step(step)

    def resume_run(self, run_id: str) -> None:
        """Load a saved run into the current chat screen."""
        self.app.save_state()
        self.clear_structured_widget()
        self.clear_activity()
        self._handler = None
        self.app.set_run_id(run_id)
        self.query_one("#chat-log", VerticalScroll).remove_children()
        self.set_input_enabled(True)
        self._start_step(self.app.current_state.current_step)
        self._focus_input()

    # -- Internal --

    def _start_step(self, step: Step) -> None:
        """Add a step divider and create the handler for this step."""
        chat_log = self.query_one("#chat-log", VerticalScroll)
        chat_log.mount(StepDivider(step))
        chat_log.scroll_end(animate=False)
        self._handler = create_handler(step, self)
        self._handler.enter()

    def _focus_input(self) -> None:
        try:
            self.query_one("#chat-input").focus()
        except Exception:
            pass

    def _focus_widget(self, widget: Widget) -> None:
        try:
            if widget.can_focus:
                widget.focus()
                return
        except Exception:
            pass
        try:
            for child in widget.query("*"):
                if getattr(child, "can_focus", False):
                    child.focus()
                    return
        except Exception:
            pass

    def action_focus_input(self) -> None:
        self._focus_input()

    def _open_resume_picker(self) -> None:
        if not self.app.persistence.list_runs():
            self.add_system_message("No saved runs available yet.")
            return
        self.app.push_screen(ResumePickerScreen(), self._handle_resume_selection)

    def _handle_resume_selection(self, run_id: str | None) -> None:
        if not run_id:
            return
        self.resume_run(run_id)

    # -- Event handlers --

    def on_input_bar_submitted(self, event: InputBar.Submitted) -> None:
        """Handle user text input from the bottom input bar."""
        event.stop()
        if not self._handler:
            return
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
                self.resume_run(state.run_id)
                return
            self._open_resume_picker()
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
