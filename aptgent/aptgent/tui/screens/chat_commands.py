from __future__ import annotations

from typing import Any

from aptgent.domain.enums import Step
from aptgent.tui.commands import SlashCommandRegistry
from aptgent.tui.steps.factory import detached_job_step_name


class ChatCommandController:
    """Slash command behavior for ``ChatScreen``."""

    def __init__(self, screen: Any) -> None:
        self.screen = screen

    def build_registry(self) -> SlashCommandRegistry:
        registry = SlashCommandRegistry()
        registry.register("/theme", lambda _screen, _arg: self.theme())
        registry.register("/resume", lambda _screen, arg: self.resume(arg))
        registry.register("/quit", lambda _screen, _arg: self.quit())
        registry.register("/cancel", lambda _screen, _arg: self.cancel())
        registry.register("/back", lambda _screen, _arg: self.back())
        registry.register("/export", lambda _screen, _arg: self.final_report("export"))
        registry.register("/finish", lambda _screen, _arg: self.final_report("finish"))
        return registry

    def theme(self) -> bool:
        self.screen._open_theme_picker()
        return True

    def resume(self, arg: str) -> bool:
        arg = arg.strip()
        if arg:
            state = self.screen.app.engine.load_run(arg)
            if state is None:
                self.screen.add_system_message(f"Saved run not found: {arg}")
                return True
            self.screen.resume_run(state.run_id)
            return True
        self.screen._open_resume_picker()
        return True

    def quit(self) -> bool:
        self.screen.app.open_quit_dialog()
        return True

    def cancel(self) -> bool:
        state = self.screen.app.current_state
        step_name = detached_job_step_name(state.current_step)
        if step_name is None:
            self.screen.add_system_message("No detachable job is running on this step.")
            return True

        persistence = self.screen.app.persistence
        cmd_file = persistence.job_cmd_file(state.run_id, step_name)

        try:
            cmd_file.parent.mkdir(parents=True, exist_ok=True)
            cmd_file.write_text("cancel")
            self.screen.add_system_message(
                f"Cancel signal sent to {step_name} job. "
                "It will stop after the current batch completes.",
                "warning-text",
            )
        except OSError as exc:
            self.screen.add_system_message(f"Failed to send cancel: {exc}", "error-text")
        return True

    def back(self) -> bool:
        state = self.screen.app.current_state
        if state.current_step != Step.PRIMARY_SCORING:
            self.screen.add_system_message("Back is only available from primary scoring.")
            return True

        from aptgent.tui.steps.empty_candidates import (
            apply_empty_candidate_recovery_ui,
            clear_site_selection_retry_feedback,
        )

        if apply_empty_candidate_recovery_ui(self.screen, state, rewind=True):
            return True

        clear_site_selection_retry_feedback(state)
        state.set_mutation_sites([])
        state.candidates = []
        state.predictions = []
        self.screen.app.save_state()
        self.screen.add_system_message(
            "Returning to site proposal. Existing recommendations will be reused.",
            "warning-text",
        )
        self.screen.rewind_to_step(
            Step.SITE_PROPOSAL,
            metadata={"reason": "user_back_from_primary_scoring"},
        )
        return True

    def final_report(self, action: str) -> bool:
        if self.screen.app.current_state.current_step != Step.FINAL_REPORT:
            return False
        command = f"/{action}"
        self.screen.add_user_message(command)
        self.screen.app.current_state.input_payload["user_text"] = command
        if self.screen._handler:
            self.screen._handler.handle_user_input(action)
        return True
