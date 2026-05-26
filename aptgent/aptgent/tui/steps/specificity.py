from __future__ import annotations

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
from aptgent.tui.widgets.chat_widgets import ProgressBubble
from aptgent.tui.widgets.structured_input import ActionMenuPanel, SpecificityPanel
from aptgent.workflow.context import record_specificity_recommendation_context


class SpecificityHandler(StepHandler):
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
        target = state.target_molecule
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

        self.screen.add_system_message(
            f"Running cross-prediction on {len(candidates)} candidates x {len(analogs)} analogs..."
        )
        self.run_worker(
            lambda: self._filter_worker(candidates, target, analogs),
            activity="Running specificity cross-prediction...",
        )

    def _filter_worker(self, candidates, target, analogs) -> None:
        all_targets = [target] + analogs
        total = len(all_targets)

        progress = ProgressBubble(total, label="Specificity Cross-Prediction")
        self.screen.app.call_from_thread(self.screen.add_structured_widget, progress)

        try:
            adapter = self.screen.app.prediction_adapter
            results_by_target: dict[str, list] = {}

            for idx, tgt in enumerate(all_targets):
                if not tgt.smiles:
                    results_by_target[tgt.smiles or ""] = []
                else:
                    results_by_target[tgt.smiles] = adapter._predict_batch_via_csv(
                        candidates, tgt
                    )
                done = idx + 1
                label = tgt.resolved_name or tgt.input_text or f"target {idx}"
                self.screen.app.call_from_thread(
                    progress.set_progress, done, f"Completed: {label}"
                )

            specificity_results: list[SpecificityResult] = []
            kept_count = 0

            for cand in candidates:
                cand_id = cand.candidate_id or ""
                failed: list[str] = []
                for analog in analogs:
                    if not analog.smiles:
                        continue
                    analog_preds = results_by_target.get(analog.smiles, [])
                    analog_pred = next(
                        (pred for pred in analog_preds if pred.candidate_id == cand_id),
                        None,
                    )
                    if analog_pred and analog_pred.label == 1:
                        failed.append(analog.input_text)

                status_str = "removed" if failed else "kept"
                if not failed:
                    kept_count += 1
                specificity_results.append(
                    SpecificityResult(
                        candidate_id=cand_id,
                        status=status_str,
                        failed_analogs=failed,
                    )
                )

            state = self.screen.app.current_state
            state.specificity_results = specificity_results
            self.screen.app.save_state()

            msg = f"Filter complete. {kept_count}/{len(candidates)} candidates kept."
            if kept_count < len(candidates):
                removed = [
                    result.candidate_id
                    for result in specificity_results
                    if result.status == "removed"
                ]
                msg += f"\nRemoved: {', '.join(removed[:10])}"

            finish_msg = f"{total} target(s) predicted — {kept_count}/{len(candidates)} kept"

            def _on_filter_complete() -> None:
                progress.finish(finish_msg)
                self.screen.add_system_message(msg)
                ns = next_step(Step.SPECIFICITY_FILTER)
                if ns:
                    self.screen.advance_to_step(ns)

            self.screen.app.call_from_thread(_on_filter_complete)
        except Exception as exc:
            self.screen.app.call_from_thread(
                self.screen.add_system_message, f"Filter failed: {exc}", "error-text"
            )
            self.screen.app.call_from_thread(self.screen.set_input_enabled, True)

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
