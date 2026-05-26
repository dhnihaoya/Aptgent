from __future__ import annotations

from typing import Any

from aptgent.domain.enums import Step
from aptgent.domain.models import SpecificityResult, TargetMolecule
from aptgent.llm.skills import AnalogSuggestionSkill
from aptgent.tui.steps.base import StepHandler
from aptgent.tui.steps.common import (
    format_specificity_recommendation_markdown,
    next_step,
    run_llm_interaction,
    validate_analog_suggestion_result,
)
from aptgent.tui.steps.job_mixin import JobAttachMixin
from aptgent.tui.widgets.chat_widgets import ProgressBubble
from aptgent.tui.widgets.structured_input import ActionMenuPanel, SpecificityPanel
from aptgent.workflow.context import record_specificity_recommendation_context


class SpecificityHandler(JobAttachMixin, StepHandler):
    """Specificity filter with detached cross-prediction job.

    The recommendation/edit phases stay in-process; once analogs are
    confirmed, the actual cross-prediction is dispatched to the detached
    ``specificity_filter`` job runner so progress streams back through the
    same ``events.jsonl`` protocol as candidate enumeration.
    """

    JOB_STEP = "specificity_filter"

    def __init__(self, screen: Any) -> None:
        super().__init__(screen)
        self._progress_done = 0
        self._progress_total = 0
        self._kept_count = 0
        self._removed_count = 0
        self._current_target = ""

    def enter(self) -> None:
        state = self.screen.app.current_state
        recommendation = state.context.specificity_recommendation
        self.screen.add_system_message(
            "Step 6: Specificity Filter\n"
            "The LLM will first suggest important analog molecules, then you can accept, edit, or replace them before filtering."
        )
        if recommendation.display_markdown and recommendation.phase in {
            "awaiting_decision",
            "editing_recommended",
            "editing_custom",
        }:
            self.screen.add_system_message(recommendation.display_markdown, markdown=True)

        if recommendation.phase == "awaiting_decision" and recommendation.analog_names:
            self._show_recommendation_choice_panel()
            self.screen.set_input_enabled(True)
        elif recommendation.phase == "editing_recommended":
            self._show_specificity_panel(
                analogs_text=self._recommended_analogs_text(),
                prefilled_recommendations=True,
            )
            self.screen.set_input_enabled(True)
        elif recommendation.phase == "editing_custom":
            self._show_specificity_panel()
            self.screen.set_input_enabled(True)
        else:
            self._suggest()
        self._refresh_input_placeholder()

    def handle_user_input(self, text: str) -> None:
        text_lower = text.strip().lower()
        if text_lower == "skip":
            self._skip()
        elif text_lower in {"accept", "1"}:
            self._accept_recommended()
        elif text_lower in {"edit", "modify", "partial", "2"}:
            self._edit_recommended()
        elif text_lower in {"custom", "3"}:
            self._customize()
        else:
            recommendation = self.screen.app.current_state.context.specificity_recommendation
            if recommendation.phase in {"editing_recommended", "editing_custom"}:
                self._run_filter(text, echo_user=False)

    def handle_structured_input(self, data: dict) -> None:
        action = data.get("action", "run")
        if action == "skip":
            self._skip()
        else:
            analogs_text = data.get("analogs_text", "")
            self._run_filter(analogs_text, echo_user=bool(analogs_text.strip()))

    def handle_action(self, action: str) -> None:
        if action == "accept-recommended-analogs":
            self._accept_recommended()
        elif action == "edit-recommended-analogs":
            self._edit_recommended()
        elif action == "custom-analogs":
            self._customize()
        elif action == "skip-specificity":
            self._skip()

    def _suggest(self) -> None:
        self.run_worker(self._suggest_worker, activity="Suggesting analog molecules...")

    def _suggest_worker(self) -> None:
        target = self.screen.app.current_state.target_molecule

        try:
            skill = AnalogSuggestionSkill()
            streamed_result: dict[str, object] = {}

            def display_stream():
                for event in skill.suggest_events(target):
                    if isinstance(event, dict) and event.get("type") == "result":
                        value = event.get("value")
                        if isinstance(value, dict):
                            streamed_result.clear()
                            streamed_result.update(value)
                        continue
                    yield event

            def structured_result() -> dict:
                if streamed_result:
                    return validate_analog_suggestion_result(streamed_result)
                raise RuntimeError("LLM structured result unavailable.")

            result = run_llm_interaction(
                self.screen,
                display_stream=display_stream,
                structured_call=structured_result,
            )
            analogs = result.get("analogs", [])
            note = result.get("note", "")
            analog_names = [a.get("name", "") for a in analogs if a.get("name")]
            markdown = format_specificity_recommendation_markdown(
                target_name=(target.resolved_name or target.input_text) if target else "",
                analogs=analogs,
                note=note,
            )
            state = self.screen.app.current_state
            record_specificity_recommendation_context(
                state,
                analog_names=analog_names,
                display_markdown=markdown,
                note=note,
                phase="awaiting_decision" if analog_names else "editing_custom",
                accepted=False,
            )
            self.screen.app.save_state()
            if markdown:
                self.screen.app.call_from_thread(
                    lambda md=markdown: self.screen.add_system_message(md, markdown=True)
                )
            if analog_names:
                self.screen.app.call_from_thread(self._show_recommendation_choice_panel)
            else:
                self.screen.app.call_from_thread(
                    self.screen.add_system_message,
                    "No analog suggestions were returned. Enter your own analogs or skip this step.",
                )
                self.screen.app.call_from_thread(self._show_specificity_panel)
            self.screen.app.call_from_thread(self.screen.set_input_enabled, True)
            self.screen.app.call_from_thread(self._refresh_input_placeholder)
        except Exception as exc:
            self.screen.app.call_from_thread(
                self.screen.add_system_message, f"Suggestion failed: {exc}", "error-text"
            )
            state = self.screen.app.current_state
            record_specificity_recommendation_context(
                state,
                analog_names=[],
                display_markdown="",
                note="",
                phase="editing_custom",
                accepted=False,
            )
            self.screen.app.save_state()
            self.screen.app.call_from_thread(self._show_specificity_panel)
            self.screen.app.call_from_thread(self.screen.set_input_enabled, True)
            self.screen.app.call_from_thread(self._refresh_input_placeholder)

    def _recommended_analogs_text(self) -> str:
        analog_names = self.screen.app.current_state.context.specificity_recommendation.analog_names
        return ", ".join(analog_names)

    def _accept_recommended(self) -> None:
        analogs_text = self._recommended_analogs_text()
        if not analogs_text:
            self.screen.add_system_message(
                "No recommended analogs are available to accept. Enter your own analogs instead.",
                "warning-text",
            )
            self._customize()
            return
        recommendation = self.screen.app.current_state.context.specificity_recommendation
        recommendation.accepted = True
        self.screen.app.save_state()
        self._run_filter(analogs_text, echo_user=False)

    def _edit_recommended(self) -> None:
        recommendation = self.screen.app.current_state.context.specificity_recommendation
        recommendation.phase = "editing_recommended"
        recommendation.accepted = False
        self.screen.app.save_state()
        self._show_specificity_panel(
            analogs_text=self._recommended_analogs_text(),
            prefilled_recommendations=True,
        )
        self.screen.set_input_enabled(True)
        self._refresh_input_placeholder()

    def _customize(self) -> None:
        recommendation = self.screen.app.current_state.context.specificity_recommendation
        recommendation.phase = "editing_custom"
        recommendation.accepted = False
        self.screen.app.save_state()
        self._show_specificity_panel()
        self.screen.set_input_enabled(True)
        self._refresh_input_placeholder()

    def _run_filter(self, analogs_text: str, *, echo_user: bool) -> None:
        if echo_user:
            self.screen.add_user_message(f"Filter with: {analogs_text}")

        state = self.screen.app.current_state
        candidates = state.candidates

        if not analogs_text.strip():
            self.screen.add_system_message("No analogs provided. Nothing to filter.")
            self.screen.set_input_enabled(True)
            return

        analogs: list[TargetMolecule] = []
        for part in analogs_text.split(","):
            part = part.strip()
            if not part:
                continue
            resolved = self.screen.app.molecule_resolver.resolve(part)
            if resolved.resolution_status == "resolved":
                analogs.append(resolved)
            else:
                analogs.append(TargetMolecule(input_text=part, resolution_status="failed"))

        state.analogs = analogs
        self.screen.app.save_state()

        self.screen.clear_structured_widget()

        valid_analogs = [a for a in analogs if a.smiles]
        all_targets_count = 1 + len(valid_analogs)
        total_pairs = len(candidates) * all_targets_count

        self.screen.add_system_message(
            f"Running cross-prediction on {len(candidates)} candidates x "
            f"{all_targets_count} target(s) ({len(valid_analogs)} analog(s) + 1 primary)."
        )

        self._progress_done = 0
        self._progress_total = total_pairs
        self._kept_count = 0
        self._removed_count = 0
        self._current_target = ""

        progress = self._create_progress_bubble(total_pairs)

        self.attach_or_spawn_job(
            on_event=lambda evt: self._on_job_event(evt, progress),
            on_done=lambda summary: self._on_job_done(summary, progress),
            on_error=lambda msg: self._on_job_error(msg),
            activity="Running specificity cross-prediction...",
        )

    def _create_progress_bubble(self, total: int) -> ProgressBubble:
        progress = ProgressBubble(total, label="Specificity Cross-Prediction")
        self.screen.add_structured_widget(progress)
        return progress

    def _on_job_event(self, evt: dict, progress: ProgressBubble) -> None:
        etype = evt.get("type", "")
        if etype == "progress":
            done = int(evt.get("done", 0))
            total = int(evt.get("total", self._progress_total))
            self._progress_done = done
            self._progress_total = total
            extra = evt.get("extra", {}) or {}
            kept = extra.get("kept")
            removed = extra.get("removed")
            current_target = extra.get("current_target")
            if isinstance(kept, int):
                self._kept_count = kept
            if isinstance(removed, int):
                self._removed_count = removed
            if isinstance(current_target, str) and current_target:
                self._current_target = current_target
            progress.set_progress(done, self._progress_info())
        elif etype == "hit":
            extra = evt.get("extra", {}) or {}
            status = extra.get("status")
            if status == "kept":
                self._kept_count += 1
            elif status == "removed":
                self._removed_count += 1
            progress.set_progress(self._progress_done, self._progress_info())

    def _progress_info(self) -> str:
        parts = [f"Progress: {self._progress_done:,}/{self._progress_total:,}"]
        parts.append(f"Kept: {self._kept_count:,}")
        parts.append(f"Removed: {self._removed_count:,}")
        if self._current_target:
            parts.append(f"Target: {self._current_target}")
        return " | ".join(parts)

    def _on_job_done(self, summary: dict, progress: ProgressBubble) -> None:
        # Reload state because the runner saves it from the detached process.
        state = self.screen.app.current_state
        self.screen.app._state = self.screen.app.engine.load_run(state.run_id)
        state = self.screen.app.current_state

        kept = int(summary.get("kept", self._kept_count))
        removed = int(summary.get("removed", self._removed_count))
        total_candidates = int(
            summary.get("candidates", len(state.candidates))
        )
        cancelled = bool(summary.get("cancelled"))

        finish_msg = f"{kept}/{total_candidates} kept ({removed} removed)"
        if cancelled:
            finish_msg += " — cancelled"
        results_path = summary.get("results_path")
        if results_path:
            finish_msg += f"\nResults: {results_path}"
        progress.finish(finish_msg)

        if cancelled:
            self.screen.add_system_message(
                "Specificity filter was cancelled. You can re-enter the step "
                "to resume from where it left off.",
                "warning-text",
            )
            self.screen.set_input_enabled(True)
            return

        msg = f"Filter complete. {kept}/{total_candidates} candidates kept."
        if removed > 0:
            removed_ids = [
                result.candidate_id
                for result in state.specificity_results
                if result.status == "removed"
            ]
            if removed_ids:
                msg += f"\nRemoved: {', '.join(removed_ids[:10])}"
        self.screen.add_system_message(msg)

        ns = next_step(Step.SPECIFICITY_FILTER)
        if ns:
            self.screen.advance_to_step(ns)

    def _on_job_error(self, msg: str) -> None:
        self.screen.add_system_message(
            f"Specificity filter failed: {msg}", "error-text"
        )
        self.screen.set_input_enabled(True)

    def _skip(self) -> None:
        state = self.screen.app.current_state
        state.specificity_results = [
            SpecificityResult(candidate_id=c.candidate_id or "", status="skipped")
            for c in state.candidates
        ]
        self.screen.app.save_state()
        self.screen.add_system_message("Specificity filter skipped.")
        ns = next_step(Step.SPECIFICITY_FILTER)
        if ns:
            self.screen.advance_to_step(ns)

    def _build_recommendation_choice_panel(self) -> ActionMenuPanel:
        return ActionMenuPanel(
            Step.SPECIFICITY_FILTER,
            "Review the recommended analogs",
            [
                (
                    "accept-recommended-analogs",
                    "Accept Recommendations",
                    "Run specificity filtering immediately with the LLM-recommended analogs.",
                ),
                (
                    "edit-recommended-analogs",
                    "Partially Accept And Edit",
                    "Open an input box prefilled with the recommended analogs so you can adjust them.",
                ),
                (
                    "custom-analogs",
                    "Reject And Customize",
                    "Ignore the recommendations and enter your own analogs from scratch.",
                ),
                (
                    "skip-specificity",
                    "Skip This Step",
                    "Continue without specificity filtering.",
                ),
            ],
        )

    def _show_recommendation_choice_panel(self) -> None:
        self.screen.add_structured_widget(self._build_recommendation_choice_panel())

    def _show_specificity_panel(
        self,
        analogs_text: str = "",
        *,
        prefilled_recommendations: bool = False,
    ) -> None:
        target = self.screen.app.current_state.target_molecule
        panel = SpecificityPanel(
            target_name=target.input_text if target else "",
            analogs_text=analogs_text,
            title="Edit Specificity Analogs" if prefilled_recommendations else "Custom Specificity Analogs",
            help_text=(
                "Review and edit the recommended analogs before running the specificity filter."
                if prefilled_recommendations
                else "Enter your own analog molecules for cross-screening. Use commas between names or SMILES."
            ),
        )
        self.screen.add_structured_widget(panel)

    def _refresh_input_placeholder(self) -> None:
        phase = self.screen.app.current_state.context.specificity_recommendation.phase
        if phase == "awaiting_decision":
            self.screen.set_input_placeholder("Type 'accept', 'edit', 'custom', or 'skip'.")
        elif phase in {"editing_recommended", "editing_custom"}:
            self.screen.set_input_placeholder("Use the analog input box below, or type 'skip' to skip this step.")
        else:
            self.screen.set_input_placeholder("Preparing analog recommendations...")
