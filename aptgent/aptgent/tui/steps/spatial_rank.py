from __future__ import annotations

from aptgent.domain.enums import Step
from aptgent.tui.steps.base import StepHandler
from aptgent.tui.steps.common import next_primary_step


class SpatialRankHandler(StepHandler):
    def enter(self) -> None:
        state = self.screen.app.current_state
        target = state.target_molecule

        if not target:
            self.screen.add_system_message("Target molecule missing.", "error-text")
            self.screen.set_input_enabled(True)
            return

        specificity_by_id = {
            result.candidate_id: result for result in state.specificity_results
        }
        excluded_ids = {
            cid
            for cid, result in specificity_by_id.items()
            if result.status == "removed"
        }

        docking_results = state.docking_results or []
        if docking_results:
            docked_ids = {result.candidate_id for result in docking_results}
            candidates = [
                candidate
                for candidate in state.candidates
                if candidate.candidate_id in docked_ids
            ]
        else:
            docked_ids = set()
            candidates = state.candidates

        # Specificity hard gate: drop candidates removed by specificity filter.
        candidates = [
            candidate
            for candidate in candidates
            if candidate.candidate_id not in excluded_ids
        ]

        # Affinity gate: only rank candidates selected by affinity top-y.
        affinity_ids = set(state.affinity_selected_ids) if state.affinity_selected_ids else set()
        if affinity_ids and docked_ids:
            candidates = [
                candidate
                for candidate in candidates
                if candidate.candidate_id in affinity_ids
            ]
            docking_results = [
                r for r in docking_results if r.candidate_id in affinity_ids
            ]

        excluded_count = len(excluded_ids & docked_ids)

        if not candidates:
            self.screen.add_system_message("No candidates available.", "error-text")
            self.screen.set_input_enabled(True)
            return

        if excluded_count:
            self.screen.add_system_message(
                f"Running spatial ranking on {len(candidates)} candidates "
                f"({excluded_count} excluded by specificity filter)..."
            )
        else:
            self.screen.add_system_message(
                f"Running spatial ranking on {len(candidates)} candidates..."
            )
        self.run_worker(
            lambda: self._rank_worker(candidates, target, docking_results),
            activity="Ranking spatial interactions...",
        )

    def _rank_worker(self, candidates, target, docking_results=None) -> None:
        try:
            results = self.screen.app.spatial_rank_adapter.rank_batch(
                candidates, target, docking_results or None
            )
            state = self.screen.app.current_state
            state.spatial_ranks = results
            self.screen.app.save_state()

            sorted_results = sorted(results, key=lambda result: result.rank)
            lines = [f"Spatial ranking complete ({len(results)} candidates):"]
            for result in sorted_results[:15]:
                groups = ", ".join(result.detected_groups[:3])
                lines.append(
                    f"  #{result.rank} {result.candidate_id}: score={result.spatial_score:.4f} groups=[{groups}]"
                )
            if len(sorted_results) > 15:
                lines.append(f"  ... and {len(sorted_results) - 15} more")

            self._threadsafe(
                self.screen.add_system_message, "\n".join(lines)
            )
            ns = next_primary_step(Step.SPATIAL_RANK)
            if ns:
                self._threadsafe(self.screen.advance_to_step, ns)
        except Exception as exc:
            self._report_error(f"Ranking failed: {exc}")
