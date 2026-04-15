from __future__ import annotations

from pathlib import Path

from aptgent.domain.enums import Step
from aptgent.tui.steps.base import StepHandler
from aptgent.tui.steps.common import next_step


class DockingRunHandler(StepHandler):
    def enter(self) -> None:
        state = self.screen.app.current_state
        plan = state.docking_plan
        target = state.target_molecule

        if not plan or plan.recommended_top_k <= 0:
            state.docking_results = []
            self.screen.app.save_state()
            self.screen.add_system_message("Docking skipped (no plan or top-k = 0).")
            ns = next_step(Step.DOCKING_RUN)
            if ns:
                self.screen.advance_to_step(ns)
            return

        if not target or not target.smiles:
            self.screen.add_system_message("Target molecule missing.", "error-text")
            self.screen.set_input_enabled(True)
            return

        if not plan.receptor_path or not Path(plan.receptor_path).exists():
            self.screen.add_system_message(
                f"Receptor file not found: {plan.receptor_path}",
                "error-text",
            )
            self.screen.set_input_enabled(True)
            return

        if not plan.grid_center or not plan.grid_size:
            self.screen.add_system_message("Grid box parameters not set.", "error-text")
            self.screen.set_input_enabled(True)
            return

        ens_preds = [p for p in state.predictions if p.model_name == "ensemble"]
        sorted_preds = sorted(
            ens_preds, key=lambda item: item.probability or 0.0, reverse=True
        )
        top_k = plan.recommended_top_k
        top_cand_ids = {pred.candidate_id for pred in sorted_preds[:top_k]}
        top_candidates = [
            candidate for candidate in state.candidates if candidate.candidate_id in top_cand_ids
        ]

        self.screen.add_system_message(
            f"Running Vina docking on {len(top_candidates)} candidates..."
        )
        self.run_worker(
            lambda: self._dock_worker(top_candidates, target),
            activity="Running docking jobs...",
        )

    def _dock_worker(self, candidates, target) -> None:
        state = self.screen.app.current_state
        plan = state.docking_plan
        try:
            work_dir = Path(state.run_id) / "docking"
            results = self.screen.app.vina_adapter.run_batch(
                candidates=candidates,
                target=target,
                receptor_pdbqt=plan.receptor_path,
                center=plan.grid_center,
                size=plan.grid_size,
                work_dir=work_dir,
            )
            state.docking_results = results
            self.screen.app.save_state()

            lines = [f"Docking complete. {len(results)} results:"]
            sorted_results = sorted(results, key=lambda result: result.docking_score or 0.0)
            for result in sorted_results[:10]:
                score_str = f"{result.docking_score:.3f}" if result.docking_score is not None else "N/A"
                lines.append(f"  {result.candidate_id}: {score_str} ({result.status})")
            if len(sorted_results) > 10:
                lines.append(f"  ... and {len(sorted_results) - 10} more")

            self.screen.app.call_from_thread(
                self.screen.add_system_message, "\n".join(lines)
            )
            ns = next_step(Step.DOCKING_RUN)
            if ns:
                self.screen.app.call_from_thread(self.screen.advance_to_step, ns)
        except Exception as exc:
            self.screen.app.call_from_thread(
                self.screen.add_system_message, f"Docking failed: {exc}", "error-text"
            )
            self.screen.app.call_from_thread(self.screen.set_input_enabled, True)
