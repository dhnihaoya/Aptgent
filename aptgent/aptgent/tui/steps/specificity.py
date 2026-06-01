from __future__ import annotations

from typing import Any

from aptgent.domain.enums import Step
from aptgent.domain.models import SpecificityResult, TargetMolecule
from aptgent.domain.ranking import select_top_y_by_affinity
from aptgent.llm.skills import AnalogParseSkill, AnalogSuggestionSkill
from aptgent.tui.steps.base import StepHandler
from aptgent.tui.steps.common import (
    format_specificity_recommendation_markdown,
    next_primary_step,
    run_llm_interaction,
    validate_analog_suggestion_result,
)
from aptgent.tui.steps.job_mixin import JobAttachMixin
from aptgent.tui.widgets.chat_widgets import ProgressBubble
from aptgent.tui.widgets.structured_input import (
    ActionMenuPanel,
    AnalogCheckboxPanel,
    AnalogCustomPanel,
)
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
        self._parse_in_flight = False

    def enter(self) -> None:
        state = self.screen.app.current_state
        self._compute_affinity_selection(state)
        recommendation = state.context.specificity_recommendation
        self.screen.add_system_message(
            "Step 7: Specificity Filter\n"
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
            target = state.target_molecule
            panel = AnalogCheckboxPanel(
                analog_names=recommendation.analog_names,
                target_name=target.input_text if target else "",
            )
            self.screen.add_structured_widget(panel)
            self.screen.set_input_enabled(True)
        elif recommendation.phase == "editing_custom":
            self.screen.set_input_enabled(True)
        else:
            self._suggest()
        self._refresh_input_placeholder()

    def handle_user_input(self, text: str) -> None:
        text_lower = text.strip().lower()
        if text_lower == "skip":
            self._skip()
        elif text_lower in {"prompt", "use prompt"}:
            self._use_intake_analogs()
        elif text_lower in {"accept", "1"}:
            self._accept_recommended()
        elif text_lower in {"edit", "modify", "partial", "2"}:
            self._edit_recommended()
        elif text_lower in {"custom", "3"}:
            self._customize()
        else:
            recommendation = self.screen.app.current_state.context.specificity_recommendation
            if recommendation.phase == "editing_custom":
                self._parse_custom_analogs(text)
            elif recommendation.phase == "editing_recommended":
                self._run_filter(text, echo_user=False)

    def handle_structured_input(self, data: dict) -> None:
        action = data.get("action", "run")
        if action == "skip":
            self._skip()
        elif action == "retry_custom":
            self._return_to_custom_input(message="Enter the analogs you want to use.")
        elif action == "back":
            self._back_to_choices()
        else:
            analogs_text = data.get("analogs_text", "")
            self._run_filter(analogs_text, echo_user=bool(analogs_text.strip()))

    def handle_action(self, action: str) -> None:
        if action == "use-intake-analogs":
            self._use_intake_analogs()
        elif action == "accept-recommended-analogs":
            self._accept_recommended()
        elif action == "edit-recommended-analogs":
            self._edit_recommended()
        elif action == "custom-analogs":
            self._customize()
        elif action == "skip-specificity":
            self._skip()

    def _compute_affinity_selection(self, state: Any) -> None:
        if state.affinity_selected_ids:
            return
        docking_results = state.docking_results
        if not docking_results:
            state.affinity_selected_ids = [
                c.candidate_id for c in state.candidates
            ]
            self.screen.app.save_state()
            return
        plan = state.docking_plan
        top_y = (
            plan.affinity_top_k
            if plan and plan.affinity_top_k
            else state.context.docking_recommendation.recommended_affinity_top_k
            or min(5, len(docking_results))
        )
        selected = select_top_y_by_affinity(
            [r.model_dump() for r in docking_results],
            top_y,
        )
        state.affinity_selected_ids = selected
        self.screen.add_system_message(
            f"Selected top-{top_y} by binding affinity: "
            f"{len(selected)} sequences (ties included)."
        )
        self.screen.app.save_state()

    def _affinity_filtered_candidates(self, state: Any) -> list[Any]:
        """Return candidates filtered to the affinity-selected subset.

        Mirrors the filtering in ``runner._run_specificity`` so the TUI
        displays counts consistent with what the detached job processes.
        """
        candidates = list(state.candidates)
        selected_ids = set(state.affinity_selected_ids) if state.affinity_selected_ids else set()
        if selected_ids:
            candidates = [c for c in candidates if c.candidate_id in selected_ids]
        return candidates

    def _suggest(self) -> None:
        self.run_worker(self._suggest_worker, activity="Suggesting analog molecules...")

    def _suggest_worker(self) -> None:
        target = self.screen.app.current_state.target_molecule

        try:
            skill = self.screen.app.runtime.create_skill(AnalogSuggestionSkill)
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
                self._threadsafe(
                    lambda md=markdown: self.screen.add_system_message(md, markdown=True)
                )
            if analog_names:
                self._threadsafe(self._show_recommendation_choice_panel)
            else:
                self._threadsafe(
                    self.screen.add_system_message,
                    "No analog suggestions were returned. Enter your own analogs or skip this step.",
                )
                self._threadsafe(self._customize)
            self._enable_input()
            self._threadsafe(self._refresh_input_placeholder)
        except Exception as exc:
            self._threadsafe(
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
            self._threadsafe(self._customize)
            self._enable_input()
            self._threadsafe(self._refresh_input_placeholder)

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

    def _use_intake_analogs(self) -> None:
        intake_analogs = self.screen.app.current_state.context.intake.analogs
        if not intake_analogs:
            self.screen.add_system_message(
                "No analogs were provided in the initial prompt.",
                "warning-text",
            )
            return
        analogs_text = ", ".join(intake_analogs)
        self.screen.add_user_message(f"Use initial prompt analogs: {analogs_text}")
        recommendation = self.screen.app.current_state.context.specificity_recommendation
        recommendation.accepted = True
        self.screen.app.save_state()
        self._run_filter(analogs_text, echo_user=False)

    def _edit_recommended(self) -> None:
        recommendation = self.screen.app.current_state.context.specificity_recommendation
        if not recommendation.analog_names:
            self.screen.add_system_message(
                "No recommended analogs to edit. Switching to custom entry.",
                "warning-text",
            )
            self._customize()
            return
        recommendation.phase = "editing_recommended"
        recommendation.accepted = False
        self.screen.app.save_state()
        target = self.screen.app.current_state.target_molecule
        panel = AnalogCheckboxPanel(
            analog_names=recommendation.analog_names,
            target_name=target.input_text if target else "",
        )
        self.screen.add_structured_widget(panel)
        self.screen.set_input_enabled(True)
        self._refresh_input_placeholder()

    def _customize(self) -> None:
        recommendation = self.screen.app.current_state.context.specificity_recommendation
        recommendation.phase = "editing_custom"
        recommendation.accepted = False
        self.screen.app.save_state()
        self.screen.clear_structured_widget()
        self.screen.set_input_enabled(True)
        self._refresh_input_placeholder()

    def _parse_custom_analogs(self, text: str) -> None:
        if self._parse_in_flight:
            return
        self._parse_in_flight = True
        self.run_worker(
            lambda: self._parse_custom_worker(text),
            activity="Parsing analog request...",
        )

    def _parse_custom_worker(self, text: str) -> None:
        try:
            skill = self.screen.app.runtime.create_skill(AnalogParseSkill)
            streamed_result: dict[str, object] = {}

            def capture_stream():
                for event in skill.parse_events(text):
                    if isinstance(event, dict) and event.get("type") == "result":
                        value = event.get("value")
                        if isinstance(value, dict):
                            streamed_result.clear()
                            streamed_result.update(value)
                        continue
                    yield event

            def structured_result() -> dict:
                if streamed_result:
                    return streamed_result
                result = skill.invoke(text)
                return result.raw if hasattr(result, "raw") else result

            result = run_llm_interaction(
                self.screen,
                display_stream=capture_stream,
                structured_call=structured_result,
            )

            molecule_names = list(dict.fromkeys(
                n for n in (m.strip() for m in result.get("molecule_names", [])) if n
            ))
            if not molecule_names:
                self._threadsafe(
                    self.screen.add_system_message,
                    "Could not identify any molecule names from your request. "
                    "Please try again with specific molecule names (e.g. 'caffeine and theobromine').",
                    "warning-text",
                )
                self._threadsafe(self._return_to_custom_input)
                return

            resolved_pairs: list[tuple[str, bool]] = []
            resolved_names: list[str] = []
            for name in molecule_names:
                resolved = self.screen.app.molecule_resolver.resolve(name)
                if resolved.resolution_status == "resolved":
                    resolved_pairs.append((name, True))
                    resolved_names.append(name)
                else:
                    resolved_pairs.append((name, False))

            if not resolved_names:
                self._threadsafe(
                    self.screen.add_system_message,
                    f"None of the identified molecules could be resolved: "
                    f"{', '.join(name for name, _ in resolved_pairs)}. "
                    "Please check the names and try again.",
                    "error-text",
                )
                self._threadsafe(self._return_to_custom_input)
                return

            def _confirm():
                self._parse_in_flight = False
                target = self.screen.app.current_state.target_molecule
                panel = AnalogCustomPanel(
                    target_name=target.input_text if target else "",
                    resolved_pairs=resolved_pairs,
                )
                self.screen.add_structured_widget(panel)

            self._threadsafe(_confirm)

        except Exception as exc:
            self._threadsafe(
                self.screen.add_system_message,
                f"Failed to parse request: {exc}",
                "error-text",
            )
            self._threadsafe(self._return_to_custom_input)

    def _return_to_custom_input(
        self,
        message: str = "Please try again with specific molecule names (e.g. 'caffeine and theobromine').",
    ) -> None:
        self._parse_in_flight = False
        self.screen.clear_structured_widget()
        self.screen.add_system_message(message, "warning-text")
        self.screen.set_input_enabled(True)
        self._refresh_input_placeholder()

    def _run_filter(self, analogs_text: str, *, echo_user: bool) -> None:
        if echo_user:
            self.screen.add_user_message(f"Filter with: {analogs_text}")

        state = self.screen.app.current_state
        candidates = self._affinity_filtered_candidates(state)

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
        self.screen.app.reload_current_state(state.run_id)
        state = self.screen.app.current_state

        kept = int(summary.get("kept", self._kept_count))
        removed = int(summary.get("removed", self._removed_count))
        total_candidates = int(
            summary.get("candidates", len(self._affinity_filtered_candidates(state)))
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

        ns = next_primary_step(Step.SPECIFICITY_FILTER)
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
            for c in self._affinity_filtered_candidates(state)
        ]
        self.screen.app.save_state()
        self.screen.add_system_message("Specificity filter skipped.")
        ns = next_primary_step(Step.SPECIFICITY_FILTER)
        if ns:
            self.screen.advance_to_step(ns)

    def _build_recommendation_choice_panel(self) -> ActionMenuPanel:
        choices: list[tuple[str, str, str]] = []
        intake_analogs = self.screen.app.current_state.context.intake.analogs
        if intake_analogs:
            choices.append(
                (
                    "use-intake-analogs",
                    "Use Initial Prompt Analogs",
                    f"Use the analogs you specified in your initial prompt: {', '.join(intake_analogs)}",
                )
            )
        choices.extend(
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
            ]
        )
        return ActionMenuPanel(
            Step.SPECIFICITY_FILTER,
            "Review the recommended analogs",
            choices,
        )

    def _show_recommendation_choice_panel(self) -> None:
        self.screen.add_structured_widget(self._build_recommendation_choice_panel())

    def _back_to_choices(self) -> None:
        recommendation = self.screen.app.current_state.context.specificity_recommendation
        recommendation.phase = "awaiting_decision"
        recommendation.accepted = False
        self.screen.app.save_state()
        self.screen.clear_structured_widget()
        self._show_recommendation_choice_panel()
        self.screen.set_input_enabled(True)
        self._refresh_input_placeholder()

    def _refresh_input_placeholder(self) -> None:
        phase = self.screen.app.current_state.context.specificity_recommendation.phase
        if phase == "awaiting_decision":
            self.screen.set_input_placeholder("Type 'accept', 'edit', 'custom', or 'skip'.")
        elif phase == "editing_custom":
            self.screen.set_input_placeholder(
                "Describe the analogs you want (e.g. 'just caffeine'), or type 'skip'."
            )
        elif phase == "editing_recommended":
            self.screen.set_input_placeholder(
                "Use the analog input box below, or type 'skip' to skip this step."
            )
        else:
            self.screen.set_input_placeholder("Preparing analog recommendations...")
