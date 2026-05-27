from __future__ import annotations

import logging
from pathlib import Path

from aptgent.domain.enums import Step
from aptgent.tui.steps.base import StepHandler
from aptgent.tui.steps.common import next_step
from aptgent.tui.steps.job_mixin import JobAttachMixin

logger = logging.getLogger(__name__)


class DockingRunHandler(JobAttachMixin, StepHandler):
    """Vina docking, runs as a detached job."""

    JOB_STEP = "docking_run"

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

        if not plan.receptor_paths:
            self.screen.add_system_message(
                "No per-candidate receptor PDBQTs were prepared.",
                "error-text",
            )
            self.screen.set_input_enabled(True)
            return

        missing_paths = [
            cid for cid, path in plan.receptor_paths.items()
            if not path or not Path(path).exists()
        ]
        if missing_paths:
            preview = ", ".join(missing_paths[:5])
            suffix = "" if len(missing_paths) <= 5 else f", \u2026 ({len(missing_paths)} total)"
            self.screen.add_system_message(
                f"Receptor files missing for: {preview}{suffix}",
                "error-text",
            )
            self.screen.set_input_enabled(True)
            return

        if not plan.grid_boxes:
            self.screen.add_system_message(
                "Grid boxes have not been computed for any candidate.",
                "error-text",
            )
            self.screen.set_input_enabled(True)
            return

        missing_boxes = [
            cid for cid in plan.receptor_paths
            if cid not in plan.grid_boxes
        ]
        if missing_boxes:
            preview = ", ".join(missing_boxes[:5])
            suffix = "" if len(missing_boxes) <= 5 else f", \u2026 ({len(missing_boxes)} total)"
            self.screen.add_system_message(
                f"Grid box parameters missing for: {preview}{suffix}",
                "error-text",
            )
            self.screen.set_input_enabled(True)
            return

        self.screen.add_system_message(
            f"Running Vina docking on top {plan.recommended_top_k} candidates..."
        )

        self.attach_or_spawn_job(
            on_event=lambda evt: self._on_job_event(evt),
            on_done=lambda summary: self._on_job_done(summary),
            on_error=lambda msg: self._on_job_error(msg),
            activity="Running docking jobs...",
        )

    def _on_job_event(self, evt: dict) -> None:
        etype = evt.get("type", "")
        if etype == "progress":
            done = evt.get("done", 0)
            total = evt.get("total", 0)
            extra = evt.get("extra", {})
            resumed = extra.get("resumed", 0)
            if resumed:
                self.screen.add_system_message(
                    f"Resuming: {resumed} already docked, {total - resumed} remaining",
                    "success-text",
                )
            self.screen.update_activity(f"Docking: {done}/{total} completed")
        elif etype == "hit":
            cand_id = evt.get("candidate_id", "?")
            score = evt.get("extra", {}).get("docking_score")
            score_str = f"{score:.3f}" if score is not None else "N/A"
            self.screen.add_system_message(f"  {cand_id}: {score_str}")

    def _on_job_done(self, summary: dict) -> None:
        # Reload state (the job runner saves it)
        state = self.screen.app.current_state
        self.screen.app.reload_current_state(state.run_id)
        state = self.screen.app.current_state

        results = state.docking_results
        lines = [f"Docking complete. {len(results)} results:"]
        sorted_results = sorted(results, key=lambda r: r.docking_score or 0.0)
        for result in sorted_results[:10]:
            score_str = f"{result.docking_score:.3f}" if result.docking_score is not None else "N/A"
            lines.append(f"  {result.candidate_id}: {score_str} ({result.status})")
        if len(sorted_results) > 10:
            lines.append(f"  ... and {len(sorted_results) - 10} more")

        self.screen.add_system_message("\n".join(lines))

        if summary.get("cancelled"):
            self.screen.add_system_message("Docking was cancelled.", "warning-text")

        ns = next_step(Step.DOCKING_RUN)
        if ns:
            self.screen.advance_to_step(ns)

    def _on_job_error(self, msg: str) -> None:
        self.screen.add_system_message(f"Docking failed: {msg}", "error-text")
        self.screen.set_input_enabled(True)
