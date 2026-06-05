from __future__ import annotations

import re
from typing import Any

from aptgent.domain.enums import Step
from aptgent.tui.steps.base import StepHandler
from aptgent.tui.steps.common import next_primary_step
from aptgent.tui.steps.common.formatting import format_enumeration_preview
from aptgent.tui.steps.empty_candidates import apply_empty_candidate_recovery_ui
from aptgent.tui.steps.job_progress import JobDoneSummary, JobEvent, JobProgressTracker
from aptgent.tui.steps.job_mixin import JobAttachMixin
from aptgent.tui.widgets.chat_widgets import ProgressBubble


class EnumerationHandler(JobAttachMixin, StepHandler):
    """Full enumeration + batch prediction, runs as a detached job."""

    JOB_STEP = "candidate_enumeration"

    def __init__(self, screen: Any) -> None:
        super().__init__(screen)
        self._progress = JobProgressTracker()

    def enter(self) -> None:
        state = self.screen.app.current_state
        sites = state.confirmed_mutation_sites

        if not sites:
            self.screen.add_system_message(
                "No mutation sites selected. Please go back.", "error-text"
            )
            self.screen.set_input_enabled(True)
            return

        total_space = 4 ** len(sites)
        enum_cfg = self.screen.app.config.get("enumeration", {})
        top_k_keep = enum_cfg.get("top_k_keep", 500)
        mutation_batch_timeout = enum_cfg.get("mutation_batch_timeout_seconds", 3600)
        effective_timeout = mutation_batch_timeout if mutation_batch_timeout > 0 else None

        self.screen.add_system_message(
            f"Mutation space: 4^{len(sites)} = {total_space:,} candidates\n"
            f"Top-K kept: {top_k_keep:,}\n"
            f"Timeout: {'none (will run until done or cancelled)' if effective_timeout is None else f'{effective_timeout}s'}"
        )

        progress = self._create_progress_bubble(total_space)

        self.attach_or_spawn_job(
            on_event=lambda evt: self._on_job_event(evt, progress),
            on_done=lambda summary: self._on_job_done(summary, progress),
            on_error=lambda msg: self._on_job_error(msg),
            activity="Enumerating and scoring candidates...",
        )

    def _on_job_event(self, evt: JobEvent, progress: ProgressBubble) -> None:
        etype = evt.get("type", "")
        if etype == "progress":
            self._progress.apply_progress(evt, counter_fields=("binding",))
            progress.set_progress(self._progress.done, self._progress_info())
        elif etype == "hit":
            self._progress.apply_probability_hit(evt)
            hit_index = self._hit_index(evt)
            if hit_index is None:
                self._progress.increment("binding")
            else:
                self._progress.set_counter(
                    "binding",
                    max(self._progress.counter("binding"), hit_index),
                )
            progress.set_progress(self._progress.done, self._progress_info())

    def _progress_info(self) -> str:
        return self._progress.format_info(
            counter_labels={"binding": "Hits"},
            include_best_probability=True,
        )

    def _hit_index(self, evt: JobEvent) -> int | None:
        candidate_id = str(evt.get("candidate_id", ""))
        match = re.fullmatch(r"hit_(\d+)", candidate_id)
        if match:
            return int(match.group(1))
        return None

    def _on_job_done(self, summary: JobDoneSummary, progress: ProgressBubble) -> None:
        state = self.reload_run_state()

        total = summary.get("total", 0)
        hits = summary.get("hits", 0)
        kept = summary.get("kept", len(state.candidates))

        msg = f"Scored {total:,} candidates, {hits:,} binding, top {kept} kept"
        if summary.get("cancelled"):
            msg += " (cancelled)"
        finish_msg = msg + f"\nResults: {summary.get('results_path', 'N/A')}"
        progress.finish(finish_msg)

        if summary.get("cancelled"):
            self.screen.add_system_message(
                "Enumeration was cancelled. Returning to site proposal so you can "
                "choose mutation sites again.",
                "warning-text",
            )
            self.screen.rewind_to_step(
                Step.SITE_PROPOSAL,
                metadata={"reason": "enumeration_cancelled"},
            )
            return

        if not summary.get("cancelled") and (hits == 0 or kept == 0):
            self._rewind_after_empty_result(state, total, hits, kept)
            return

        self._show_preview(state.candidates, state.predictions)

        ns = next_primary_step(Step.CANDIDATE_ENUMERATION)
        if ns:
            self.screen.advance_to_step(ns)

    def _on_job_error(self, msg: str) -> None:
        self._report_error(f"Enumeration failed: {msg}")

    def _create_progress_bubble(self, total_space: int) -> ProgressBubble:
        progress = ProgressBubble(total_space, label="Enumerating & Scoring")
        self.screen.add_structured_widget(progress)
        return progress

    def _show_preview(self, candidates, predictions) -> None:
        preview = format_enumeration_preview(candidates, predictions)
        if preview:
            self.screen.add_system_message(preview)

    def _rewind_after_empty_result(
        self,
        state: Any,
        total: int,
        hits: int,
        kept: int,
    ) -> None:
        apply_empty_candidate_recovery_ui(
            self.screen, state, total=total, hits=hits, kept=kept, rewind=True,
        )
