from __future__ import annotations

from typing import Any

from aptgent.domain.enums import Step
from aptgent.domain.ranking import rank_sums_from_model_probs
from aptgent.tui.steps.base import StepHandler
from aptgent.tui.steps.common import next_primary_step
from aptgent.tui.steps.common.formatting import format_ranked_candidates
from aptgent.tui.steps.empty_candidates import apply_empty_candidate_recovery_ui


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
            self._report_error("No candidates available.")
            return

        if state.predictions:
            self._show_existing(state)
            return

        if not target or not target.smiles:
            self._report_error("Target molecule missing. Cannot score.")
            return

        self.screen.add_system_message(
            f"Running ensemble prediction on {len(candidates)} candidates..."
        )
        self.run_worker(self._score, activity="Running ensemble prediction...")

    def _show_existing(self, state: Any) -> None:
        ens_preds = [p for p in state.predictions if p.model_name == "ensemble"]
        sorted_preds = sorted(
            ens_preds,
            key=lambda item: item.raw_outputs.get("cumulative_rank", float("inf")),
        )
        lines = [
            f"Scoring already completed during enumeration "
            f"({len(sorted_preds)} candidates):"
        ]
        lines.append(format_ranked_candidates(sorted_preds))
        self.screen.add_system_message("\n".join(lines))
        ns = next_primary_step(Step.PRIMARY_SCORING)
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

            ens_preds = [p for p in results if p.model_name == "ensemble" and p.label == 1]

            # Collect per-model probabilities for rank_sum computation.
            per_candidate_probs: list[list[float]] = []
            valid_indices: list[int] = []
            for idx, pred in enumerate(ens_preds):
                individual = pred.raw_outputs.get("individual", {})
                if not individual:
                    continue
                probs = [v.get("probability", 0.0) for v in individual.values()]
                per_candidate_probs.append(probs)
                valid_indices.append(idx)

            if per_candidate_probs:
                rank_sums = rank_sums_from_model_probs(per_candidate_probs)
                for i, pred_idx in enumerate(valid_indices):
                    ens_preds[pred_idx].raw_outputs["rank_sum"] = rank_sums[i]

            # Sort: candidates with rank_sum first (ascending), then by probability descending.
            def _sort_key(item: Any) -> tuple:
                rs = item.raw_outputs.get("rank_sum")
                return (0, rs) if rs is not None else (1, -(item.probability or 0.0))

            sorted_preds = sorted(ens_preds, key=_sort_key)

            # Assign cumulative_rank using dense ranking on rank_sum.
            prev_rs: int | None = None
            cumulative_rank = 0
            for pred in sorted_preds:
                if "rank_sum" in pred.raw_outputs:
                    rs = pred.raw_outputs["rank_sum"]
                    if prev_rs is None or rs != prev_rs:
                        cumulative_rank += 1
                        prev_rs = rs
                    pred.raw_outputs["cumulative_rank"] = cumulative_rank

            self.screen.app.save_state()

            lines = [f"Scored {len(sorted_preds)} candidates (ensemble):"]
            lines.append(format_ranked_candidates(sorted_preds))

            self._threadsafe(
                self.screen.add_system_message, "\n".join(lines)
            )
            ns = next_primary_step(Step.PRIMARY_SCORING)
            if ns:
                self._threadsafe(self.screen.advance_to_step, ns)
        except Exception as exc:
            self._report_error(f"Scoring failed: {exc}")

    def _handle_empty_candidates(self, state: Any) -> bool:
        return apply_empty_candidate_recovery_ui(self.screen, state)
