from __future__ import annotations

from aptgent.domain.enums import Step
from aptgent.domain.models import SpecificityResult, TargetMolecule
from aptgent.llm.skills import AnalogSuggestionSkill
from aptgent.tui.steps.base import StepHandler
from aptgent.tui.steps.common import (
    next_step,
    run_llm_interaction,
    validate_analog_suggestion_result,
)
from aptgent.tui.widgets.structured_input import ActionMenuPanel, SpecificityPanel


class SpecificityHandler(StepHandler):
    def enter(self) -> None:
        self.screen.add_system_message(
            "Step 6: Specificity Filter\n"
            "You can provide analog molecules, ask the LLM to suggest them, or skip this step."
        )
        self.screen.add_structured_widget(self._build_choice_panel())
        self.screen.set_input_enabled(True)
        self.screen.set_input_placeholder("Type 'skip', 'suggest', or analog names (comma-separated).")

    def handle_user_input(self, text: str) -> None:
        text_lower = text.strip().lower()
        if text_lower == "skip":
            self._skip()
        elif text_lower == "suggest":
            self._show_specificity_panel()
            self._suggest()
        else:
            self._run_filter(text, echo_user=False)

    def handle_structured_input(self, data: dict) -> None:
        action = data.get("action", "run")
        if action == "skip":
            self._skip()
        elif action == "suggest":
            self._suggest()
        else:
            analogs_text = data.get("analogs_text", "")
            self._run_filter(analogs_text, echo_user=bool(analogs_text.strip()))

    def handle_action(self, action: str) -> None:
        if action in {"suggest", "suggest-analogs"}:
            self._show_specificity_panel()
            self._suggest()
        elif action == "custom-analogs":
            self._show_specificity_panel()
            self.screen.set_input_enabled(True)
        elif action == "skip-specificity":
            self._skip()

    def _suggest(self) -> None:
        self.run_worker(self._suggest_worker, activity="Suggesting analog molecules...")

    def _suggest_worker(self) -> None:
        target = self.screen.app.current_state.target_molecule

        try:
            skill = AnalogSuggestionSkill()
            result = run_llm_interaction(
                self.screen,
                display_stream=lambda: skill.explain_suggest_stream(target),
                structured_call=lambda: validate_analog_suggestion_result(skill.suggest(target)),
            )
            analogs = result.get("analogs", [])
            names = ", ".join(a.get("name", "") for a in analogs if a.get("name"))
            self.screen.app.call_from_thread(
                self.screen.add_system_message,
                f"Loaded suggested analogs into the input field: {names}" if names else "No analog suggestions were returned.",
            )
            self.screen.app.call_from_thread(self._update_analog_input, names)
            self.screen.app.call_from_thread(self.screen.set_input_enabled, True)
        except Exception as exc:
            self.screen.app.call_from_thread(
                self.screen.add_system_message, f"Suggestion failed: {exc}", "error-text"
            )
            self.screen.app.call_from_thread(self.screen.set_input_enabled, True)

    def _update_analog_input(self, names: str) -> None:
        try:
            panel = self.screen.query_one(SpecificityPanel)
            panel.query_one("#analog-input").value = names
        except Exception:
            pass

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

        self.screen.add_system_message(
            f"Running cross-prediction on {len(candidates)} candidates x {len(analogs)} analogs..."
        )
        self.run_worker(
            lambda: self._filter_worker(candidates, target, analogs),
            activity="Running specificity cross-prediction...",
        )

    def _filter_worker(self, candidates, target, analogs) -> None:
        try:
            results_by_target = self.screen.app.prediction_adapter.predict_batch_for_targets(
                candidates, [target] + analogs
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

            self.screen.app.call_from_thread(self.screen.add_system_message, msg)
            ns = next_step(Step.SPECIFICITY_FILTER)
            if ns:
                self.screen.app.call_from_thread(self.screen.advance_to_step, ns)
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

    def _build_choice_panel(self) -> ActionMenuPanel:
        return ActionMenuPanel(
            Step.SPECIFICITY_FILTER,
            "Choose how to provide analog molecules",
            [
                (
                    "suggest-analogs",
                    "Use Recommended Analogs",
                    "Ask the LLM for likely confounding analog molecules, then review them.",
                ),
                (
                    "custom-analogs",
                    "Enter My Own Analogs",
                    "Open a focused input panel and provide comma-separated names or SMILES.",
                ),
                (
                    "skip-specificity",
                    "Skip This Step",
                    "Continue without specificity filtering.",
                ),
            ],
        )

    def _show_specificity_panel(self, analogs_text: str = "") -> None:
        target = self.screen.app.current_state.target_molecule
        panel = SpecificityPanel(
            target_name=target.input_text if target else "",
            analogs_text=analogs_text,
        )
        self.screen.add_structured_widget(panel)
