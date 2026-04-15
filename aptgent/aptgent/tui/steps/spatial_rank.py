from __future__ import annotations

from aptgent.domain.enums import Step
from aptgent.tui.steps.base import StepHandler
from aptgent.tui.steps.common import next_step


class SpatialRankHandler(StepHandler):
    def enter(self) -> None:
        state = self.screen.app.current_state
        target = state.target_molecule

        if not target:
            self.screen.add_system_message("Target molecule missing.", "error-text")
            self.screen.set_input_enabled(True)
            return

        if state.docking_results:
            docked_ids = {result.candidate_id for result in state.docking_results}
            candidates = [
                candidate for candidate in state.candidates if candidate.candidate_id in docked_ids
            ]
        else:
            candidates = state.candidates

        if not candidates:
            self.screen.add_system_message("No candidates available.", "error-text")
            self.screen.set_input_enabled(True)
            return

        self.screen.add_system_message(
            f"Running spatial ranking on {len(candidates)} candidates..."
        )
        self.run_worker(
            lambda: self._rank_worker(candidates, target),
            activity="Ranking spatial interactions...",
        )

    def _rank_worker(self, candidates, target) -> None:
        try:
            results = self.screen.app.spatial_rank_adapter.rank_batch(candidates, target)
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

            self.screen.app.call_from_thread(
                self.screen.add_system_message, "\n".join(lines)
            )
            ns = next_step(Step.SPATIAL_RANK)
            if ns:
                self.screen.app.call_from_thread(self.screen.advance_to_step, ns)
        except Exception as exc:
            self.screen.app.call_from_thread(
                self.screen.add_system_message, f"Ranking failed: {exc}", "error-text"
            )
            self.screen.app.call_from_thread(self.screen.set_input_enabled, True)
