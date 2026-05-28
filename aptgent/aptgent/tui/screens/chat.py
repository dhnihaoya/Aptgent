from __future__ import annotations

import logging

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.css.query import NoMatches
from textual.screen import Screen
from textual.widget import Widget

from aptgent.domain.enums import Step
from aptgent.tui.commands import SlashCommandRegistry, commands_for_step
from aptgent.tui.screens.resume import ResumePickerScreen
from aptgent.tui.screens.theme_picker import ThemePickerScreen
from aptgent.tui.steps import StepHandler, create_handler
from aptgent.tui.widgets.chat_widgets import (
    ActivityBubble,
    InputBar,
    StepDivider,
    StreamingBubble,
    SystemBubble,
    ThinkingBubble,
    UserBubble,
)
from aptgent.tui.widgets.structured_input import StructuredActionRequested, StructuredInputSubmitted
from aptgent.workflow.engine import TRANSITIONS

_log = logging.getLogger(__name__)


class ChatScreen(Screen):
    """Single screen that hosts the entire workflow as a chat conversation."""

    BINDINGS = [
        Binding("escape", "request_quit", "Quit", show=False),
        Binding("ctrl+o", "toggle_thinking", "Toggle Thinking", show=False),
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
        self._slash_commands = self._build_slash_commands()

    def _build_slash_commands(self) -> SlashCommandRegistry:
        registry = SlashCommandRegistry()
        registry.register("/theme", lambda screen, _arg: screen._cmd_theme())
        registry.register("/resume", lambda screen, arg: screen._cmd_resume(arg))
        registry.register("/quit", lambda screen, _arg: screen._cmd_quit())
        registry.register("/cancel", lambda screen, _arg: screen._cmd_cancel())
        registry.register("/back", lambda screen, _arg: screen._cmd_back())
        registry.register("/export", lambda screen, _arg: screen._cmd_final_report("export"))
        registry.register("/finish", lambda screen, _arg: screen._cmd_final_report("finish"))
        return registry

    def _cmd_theme(self) -> bool:
        self._open_theme_picker()
        return True

    def _cmd_resume(self, arg: str) -> bool:
        arg = arg.strip()
        if arg:
            state = self.app.engine.load_run(arg)
            if state is None:
                self.add_system_message(f"Saved run not found: {arg}")
                return True
            self.resume_run(state.run_id)
            return True
        self._open_resume_picker()
        return True

    def _cmd_quit(self) -> bool:
        self.app.open_quit_dialog()
        return True

    def _cmd_cancel(self) -> bool:
        state = self.app.current_state
        step_name = None
        if state.current_step == Step.CANDIDATE_ENUMERATION:
            step_name = "candidate_enumeration"
        elif state.current_step == Step.DOCKING_RUN:
            step_name = "docking_run"
        elif state.current_step == Step.SPECIFICITY_FILTER:
            step_name = "specificity_filter"

        if step_name is None:
            self.add_system_message("No detachable job is running on this step.")
            return True

        persistence = self.app.persistence
        cmd_file = persistence.job_cmd_file(state.run_id, step_name)

        try:
            cmd_file.parent.mkdir(parents=True, exist_ok=True)
            cmd_file.write_text("cancel")
            self.add_system_message(
                f"Cancel signal sent to {step_name} job. "
                "It will stop after the current batch completes.",
                "warning-text",
            )
        except OSError as exc:
            self.add_system_message(f"Failed to send cancel: {exc}", "error-text")
        return True

    def _cmd_back(self) -> bool:
        state = self.app.current_state
        if state.current_step != Step.PRIMARY_SCORING:
            self.add_system_message("Back is only available from primary scoring.")
            return True

        from aptgent.tui.steps.empty_candidates import (
            clear_site_selection_retry_feedback,
            is_empty_enumeration_result,
            prepare_empty_candidate_recovery,
        )

        if is_empty_enumeration_result(state):
            recovery = prepare_empty_candidate_recovery(state)
            self.app.save_state()
            if recovery.needs_regeneration:
                self.add_system_message(
                    "No predicted binding mutations were found for the selected LLM plan. "
                    "Returning to site proposal so the LLM can revise the recommendation.",
                    "warning-text",
                )
            else:
                self.add_system_message(
                    "No predicted binding mutations were found for the selected custom sites. "
                    "Returning to site proposal so you can choose a different set."
                )
            self.rewind_to_step(
                Step.SITE_PROPOSAL,
                metadata={"reason": "no_positive_candidates"},
            )
            return True

        proposal = state.context.site_proposal
        clear_site_selection_retry_feedback(state)
        state.confirmed_mutation_sites = []
        state.candidates = []
        state.predictions = []
        self.app.save_state()
        self.add_system_message(
            "Returning to site proposal. Existing recommendations will be reused.",
            "warning-text",
        )
        self.rewind_to_step(
            Step.SITE_PROPOSAL,
            metadata={"reason": "user_back_from_primary_scoring"},
        )
        return True

    def _cmd_final_report(self, action: str) -> bool:
        if self.app.current_state.current_step != Step.FINAL_REPORT:
            return False
        command = f"/{action}"
        self.add_user_message(command)
        self.app.current_state.input_payload["user_text"] = command
        if self._handler:
            self._handler.handle_user_input(action)
        return True

    def compose(self) -> ComposeResult:
        yield self.app.progress_bar
        yield self.app.status_panel
        yield VerticalScroll(id="chat-log")
        yield InputBar(id="input-bar")

    def on_mount(self) -> None:
        state = self.app.current_state
        step = state.current_step
        self._start_step(step)
        self.set_timer(0.1, self._focus_initial_target)
        pending_text = self.app.consume_pending_start_message()
        if pending_text:
            self.call_after_refresh(lambda: self._submit_pending_message(pending_text))

    # -- Public API for step handlers --

    def add_system_message(
        self,
        text: str,
        extra_class: str = "",
        markdown: bool = False,
    ) -> SystemBubble:
        """Append a system bubble to the chat log."""
        bubble = SystemBubble(text, markdown=markdown)
        if extra_class:
            bubble.add_class(extra_class)
        self._mount_bubble(bubble)
        return bubble

    def add_tool_message(
        self,
        text: str,
        *,
        label: str = "tool",
        markdown: bool = True,
    ) -> SystemBubble:
        body = f"`{label}`\n\n{text}" if markdown else f"[{label}] {text}"
        return self.add_system_message(body, extra_class="tool-bubble", markdown=markdown)

    def add_streaming_message(self, *, markdown: bool = False) -> StreamingBubble:
        """Append a streaming bubble to the chat log and return it."""
        bubble = StreamingBubble(markdown=markdown)
        self._mount_bubble(bubble)
        return bubble

    def add_thinking_message(self) -> ThinkingBubble:
        """Append a collapsible thinking bubble to the chat log and return it."""
        bubble = ThinkingBubble()
        self._mount_bubble(bubble)
        return bubble

    def add_user_message(self, text: str) -> None:
        """Append a user bubble to the chat log."""
        chat_log = self.query_one("#chat-log", VerticalScroll)
        follow_output = self._should_follow_output(chat_log)
        chat_log.mount(UserBubble(text))
        self._follow_output_if_needed(chat_log, follow_output)

    def add_structured_widget(self, widget) -> None:
        """Mount a structured input widget into the chat log."""
        self.clear_structured_widget()
        self._active_structured_widget = widget
        self._mount_bubble(widget)
        self.call_after_refresh(lambda: self._focus_widget(widget))

    def clear_structured_widget(self) -> None:
        widget = self._active_structured_widget
        if widget is not None:
            try:
                if widget.is_mounted:
                    widget.remove()
            except Exception:
                _log.debug(
                    "Failed to remove structured widget; treating as already detached",
                    exc_info=True,
                )
        self._active_structured_widget = None

    def show_activity(self, text: str) -> None:
        chat_log = self.query_one("#chat-log", VerticalScroll)
        follow_output = self._should_follow_output(chat_log)
        if self._activity_bubble is None or not self._activity_bubble.is_mounted:
            self._activity_bubble = ActivityBubble(text)
            chat_log.mount(self._activity_bubble)
        else:
            self._activity_bubble.set_text(text)
        self._follow_output_if_needed(chat_log, follow_output)

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
                _log.debug(
                    "Failed to remove activity bubble; treating as already detached",
                    exc_info=True,
                )
            self._activity_bubble = None

    def set_input_enabled(self, enabled: bool) -> None:
        try:
            self.query_one("#input-bar", InputBar).set_enabled(enabled)
        except NoMatches:
            _log.debug("input-bar not mounted", exc_info=True)
        if enabled:
            self.clear_activity()

    def set_input_placeholder(self, text: str) -> None:
        try:
            self.query_one("#input-bar", InputBar).set_placeholder(text)
        except NoMatches:
            _log.debug("input-bar not mounted", exc_info=True)

    def advance_to_step(self, step: Step) -> None:
        """Transition to the next step in the chat."""
        state = self.app.current_state
        if step == state.current_step:
            allowed = TRANSITIONS.get(state.current_step, [])
            if step in allowed:
                self.app.engine.transition_to(
                    state,
                    step,
                    metadata={"reenter": True},
                )
            else:
                _log.warning(
                    "Ignored self-transition for step %s because it is not allowed from %s.",
                    step.value,
                    state.current_step.value,
                )
                return
        else:
            self.app.engine.transition_to(state, step)
        self.app.progress_bar.set_step(step)
        self.app.save_state()
        self.clear_structured_widget()
        self.clear_activity()
        self._start_step(step)

    def rewind_to_step(self, step: Step, metadata: dict | None = None) -> None:
        """Move back to an earlier workflow step outside the normal transition DAG."""
        from aptgent.tui.steps.state_reset import _reset_candidate_outputs

        state = self.app.current_state
        self.app.engine.rewind_to(state, step, metadata=metadata)
        if step == Step.SITE_PROPOSAL:
            _reset_candidate_outputs(state)
        self.app.progress_bar.set_step(step)
        self.app.save_state()
        self.clear_structured_widget()
        self.clear_activity()
        self._start_step(step)

    def resume_run(self, run_id: str) -> None:
        """Load a saved run into the current chat screen.

        If the run has a running detached job (enumeration or docking),
        skip directly to that step and attach.
        """
        self.app.save_state()
        self.clear_structured_widget()
        self.clear_activity()
        self._handler = None
        self.app.set_run_id(run_id)
        self.query_one("#chat-log", VerticalScroll).remove_children()
        self.set_input_enabled(True)

        state = self.app.current_state
        target_step = self._detect_resume_target(state)
        if target_step is not None:
            self.add_system_message(
                f"Resuming run — jumping to active step: {target_step.value}"
            )
            self._start_step(target_step)
        else:
            self._start_step(state.current_step)

        self._focus_input()

    def _detect_resume_target(self, state) -> Step | None:
        """Detect which step to resume at, considering detached jobs."""
        from aptgent.tui.steps.job_mixin import is_job_alive

        persistence = self.app.persistence
        run_id = state.run_id
        current = state.current_step

        # Check enumeration job status
        if current in (Step.CANDIDATE_ENUMERATION, Step.PRIMARY_SCORING,
                       Step.SPECIFICITY_FILTER, Step.DOCKING_SELECTION,
                       Step.DOCKING_RUN, Step.SPATIAL_RANK, Step.FINAL_REPORT):
            if is_job_alive(persistence, run_id, "candidate_enumeration"):
                self.add_system_message("Enumeration job is still running, attaching...")
                return Step.CANDIDATE_ENUMERATION

        # Check docking job status
        if current in (Step.DOCKING_RUN, Step.SPATIAL_RANK, Step.FINAL_REPORT):
            if is_job_alive(persistence, run_id, "docking_run"):
                self.add_system_message("Docking job is still running, attaching...")
                return Step.DOCKING_RUN

        return None

    # -- Internal --

    def _start_step(self, step: Step) -> None:
        """Add a step divider and create the handler for this step."""
        chat_log = self.query_one("#chat-log", VerticalScroll)
        follow_output = self._should_follow_output(chat_log)
        chat_log.mount(StepDivider(step))
        self._follow_output_if_needed(chat_log, follow_output)
        self.query_one("#input-bar", InputBar).set_commands(commands_for_step(step))
        self._handler = create_handler(step, self)
        self._handler.enter()

    def _focus_input(self) -> None:
        try:
            self.query_one("#chat-input").focus()
        except NoMatches:
            _log.debug("chat-input not mounted", exc_info=True)

    def _focus_initial_target(self) -> None:
        if self._active_structured_widget is not None:
            self._focus_widget(self._active_structured_widget)
            return
        self._focus_input()

    def _focus_widget(self, widget: Widget) -> None:
        try:
            if widget.can_focus:
                widget.focus()
                return
        except Exception:
            _log.debug("Failed to focus widget directly", exc_info=True)
        try:
            for child in widget.query("*"):
                if getattr(child, "can_focus", False):
                    child.focus()
                    return
        except Exception:
            _log.debug("Failed to focus descendant widget", exc_info=True)

    def _mount_bubble(self, bubble: Widget) -> None:
        """Mount *bubble* into the chat log, inserting before the activity bubble if present."""
        chat_log = self.query_one("#chat-log", VerticalScroll)
        follow_output = self._should_follow_output(chat_log)
        if self._activity_bubble is not None and self._activity_bubble.is_mounted:
            chat_log.mount(bubble, before=self._activity_bubble)
        else:
            chat_log.mount(bubble)
        self._follow_output_if_needed(chat_log, follow_output)

    def _should_follow_output(self, chat_log: VerticalScroll) -> bool:
        try:
            return chat_log.max_scroll_y <= 0 or chat_log.is_vertical_scroll_end
        except Exception:
            return True

    def _follow_output_if_needed(
        self,
        chat_log: VerticalScroll,
        should_follow: bool,
    ) -> None:
        if should_follow:
            chat_log.scroll_end(animate=False)

    def action_focus_input(self) -> None:
        self._focus_input()

    def action_toggle_thinking(self) -> None:
        chat_log = self.query_one("#chat-log", VerticalScroll)
        for child in reversed(chat_log.children):
            if isinstance(child, ThinkingBubble) and child.has_content:
                child.toggle()
                return

    def action_request_quit(self) -> None:
        input_bar = self.query_one("#input-bar", InputBar)
        if input_bar.command_palette_open():
            input_bar.close_command_palette()
            return
        self.app.open_quit_dialog()

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
        self.resume_run(run_id)

    def _handle_theme_selection(self, theme_name: str | None) -> None:
        if not theme_name:
            self._focus_input()
            return
        label = self.app.apply_theme(theme_name)
        if label is not None:
            self.add_system_message(f"Theme switched to {label}.")
        self._focus_input()

    def _submit_pending_message(self, text: str) -> None:
        if not self._handler:
            return
        self.add_user_message(text)
        self.app.current_state.input_payload["user_text"] = text
        self._handler.handle_user_input(text)

    # -- Event handlers --

    def on_input_bar_submitted(self, event: InputBar.Submitted) -> None:
        """Handle user text input from the bottom input bar."""
        event.stop()
        if not self._handler:
            return
        text = event.value.strip()
        if not text:
            return
        dispatch_result = self._slash_commands.dispatch(self, text)
        if dispatch_result is True:
            return
        if dispatch_result is False:
            command = text.split(" ", 1)[0]
            self.add_system_message(f"Unknown command: {command}")
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
