from __future__ import annotations

from aptgent.domain.enums import Step
from aptgent.tui.steps.common import next_primary_step
from aptgent.tui.steps.job_progress import JobDoneSummary, JobEvent, _event_extra
from aptgent.tui.widgets.chat_widgets import ProgressBubble


class SpecificityProgressMixin:
    """Detached job progress handling for the specificity step."""

    def _create_progress_bubble(self, total: int) -> ProgressBubble:
        progress = ProgressBubble(total, label="Specificity Cross-Prediction")
        self.screen.add_structured_widget(progress)
        return progress

    def _on_job_event(self, evt: JobEvent, progress: ProgressBubble) -> None:
        etype = evt.get("type", "")
        if etype == "progress":
            self._progress.apply_progress(
                evt,
                counter_fields=("kept", "removed"),
            )
            progress.set_progress(self._progress.done, self._progress_info())
        elif etype == "hit":
            extra = _event_extra(evt)
            status = extra.get("status")
            if status == "kept":
                self._progress.increment("kept")
            elif status == "removed":
                self._progress.increment("removed")
            progress.set_progress(self._progress.done, self._progress_info())

    def _progress_info(self) -> str:
        return self._progress.format_info(
            counter_labels={"kept": "Kept", "removed": "Removed"},
            include_current_target=True,
        )

    def _on_job_done(self, summary: JobDoneSummary, progress: ProgressBubble) -> None:
        state = self.reload_run_state()

        kept = int(summary.get("kept", self._progress.counter("kept")))
        removed = int(summary.get("removed", self._progress.counter("removed")))
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
        self._report_error(f"Specificity filter failed: {msg}")
