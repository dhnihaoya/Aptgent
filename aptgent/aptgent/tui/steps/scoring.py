from __future__ import annotations

from typing import Any

from aptgent.domain.enums import Step
from aptgent.tui.steps.base import StepHandler
from aptgent.tui.steps.common import next_step


class ScoringHandler(StepHandler):
    """Fallback scoring step.

    When the fast enumeration path is used, predictions are produced
    during enumeration and this step becomes a pure display (no worker).
    The ``_score`` worker only runs when ``state.predictions`` is empty,
    i.e. the degraded / legacy path without integrated scoring.
    """

    def enter(self) -> None:
        state = self.screen.app.current_state
        candidates = state.candidates
        target = state.target_molecule

        if not candidates:
            if self._handle_empty_candidates(state):
                return
            self.screen.add_system_message("No candidates available.", "error-text")
            self.screen.set_input_enabled(True)
            return

        if state.predictions:
            self._show_existing(state)
            return

        if not target or not target.smiles:
            self.screen.add_system_message(
                "Target molecule missing. Cannot score.", "error-text"
            )
            self.screen.set_input_enabled(True)
            return

        self.screen.add_system_message(
            f"Running ensemble prediction on {len(candidates)} candidates..."
        )
        self.run_worker(self._score, activity="Running ensemble prediction...")

    def _show_existing(self, state: Any) -> None:
        ens_preds = [p for p in state.predictions if p.model_name == "ensemble"]
        sorted_preds = sorted(
            ens_preds, key=lambda item: item.probability or 0.0, reverse=True
        )
        lines = [
            f"Scoring already completed during enumeration "
            f"({len(sorted_preds)} candidates):"
        ]
        for pred in sorted_preds[:10]:
            label_str = "Binding" if pred.label == 1 else "Non-binding"
            lines.append(
                f"  {pred.candidate_id}: {label_str} (P={pred.probability:.4f})"
            )
        if len(sorted_preds) > 10:
            lines.append(f"  ... and {len(sorted_preds) - 10} more")
        self.screen.add_system_message("\n".join(lines))
        ns = next_step(Step.PRIMARY_SCORING)
        if ns:
            self.screen.advance_to_step(ns)

    def _score(self) -> None:
        state = self.screen.app.current_state
        candidates = state.candidates
        target = state.target_molecule

        try:
            results = self.screen.app.prediction_adapter.predict_batch(candidates, target)
            state.predictions = results
            self.screen.app.save_state()

            ens_preds = [p for p in results if p.model_name == "ensemble"]
            sorted_preds = sorted(
                ens_preds, key=lambda item: item.probability or 0.0, reverse=True
            )

            lines = [f"Scored {len(sorted_preds)} candidates (ensemble):"]
            for pred in sorted_preds[:10]:
                label_str = "Binding" if pred.label == 1 else "Non-binding"
                lines.append(
                    f"  {pred.candidate_id}: {label_str} (P={pred.probability:.4f})"
                )
            if len(sorted_preds) > 10:
                lines.append(f"  ... and {len(sorted_preds) - 10} more")

            self.screen.app.call_from_thread(
                self.screen.add_system_message, "\n".join(lines)
            )
            ns = next_step(Step.PRIMARY_SCORING)
            if ns:
                self.screen.app.call_from_thread(self.screen.advance_to_step, ns)
        except Exception as exc:
            self.screen.app.call_from_thread(
                self.screen.add_system_message, f"Scoring failed: {exc}", "error-text"
            )
            self.screen.app.call_from_thread(self.screen.set_input_enabled, True)

    def _handle_empty_candidates(self, state: Any) -> bool:
        context = state.context.site_proposal
        feedback = dict(context.extra_context.get("site_selection_feedback") or {})
        is_no_positive = (
            feedback.get("reason") == "no_positive_candidates"
            or bool(context.regeneration_reason)
        )
        if not is_no_positive:
            return False

        if context.selection_source == "llm" or context.needs_regeneration:
            if not context.needs_regeneration:
                context.needs_regeneration = True
            if not context.regeneration_reason:
                context.regeneration_reason = (
                    feedback.get("message")
                    or "No predicted binding mutations were found for the selected LLM plan."
                )
            self.screen.app.save_state()
            self.screen.add_system_message(
                "No predicted binding mutations were found for the selected LLM plan. "
                "Returning to site proposal so the LLM can revise the recommendation.",
                "warning-text",
            )
            self.screen.rewind_to_step(
                Step.SITE_PROPOSAL,
                metadata={"reason": "no_positive_candidates"},
            )
            return True

        self.screen.add_system_message(
            "No predicted binding mutations were found for the selected custom sites. "
            "Choose a different set of mutation sites, use /resume to open another saved run, "
            "or use /quit to exit."
        )
        self.screen.set_input_enabled(True)
        return True
