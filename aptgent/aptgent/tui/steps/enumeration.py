from __future__ import annotations

import re
from typing import Any

from aptgent.domain.enums import Step
from aptgent.tui.steps.base import StepHandler
from aptgent.tui.steps.common import next_step
from aptgent.tui.steps.empty_candidates import prepare_empty_candidate_recovery
from aptgent.tui.steps.job_mixin import JobAttachMixin
from aptgent.tui.widgets.chat_widgets import ProgressBubble
from aptgent.workflow.context import get_sequence


class EnumerationHandler(JobAttachMixin, StepHandler):
    """Full enumeration + batch prediction, runs as a detached job."""

    JOB_STEP = "candidate_enumeration"

    def __init__(self, screen: Any) -> None:
        super().__init__(screen)
        self._progress_done = 0
        self._progress_total = 0
        self._hit_count = 0
        self._best_probability: float | None = None

    def enter(self) -> None:
        state = self.screen.app.current_state
        sites = state.confirmed_mutation_sites

        if not sites:
            self.screen.add_system_message(
                "No mutation sites selected. Please go back.", "error-text"
            )
            self.screen.set_input_enabled(True)
            return

        seq: str = get_sequence(state) or ""
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

    def _on_job_event(self, evt: dict, progress: ProgressBubble) -> None:
        etype = evt.get("type", "")
        if etype == "progress":
            done = evt.get("done", 0)
            total = evt.get("total", 0)
            self._progress_done = done
            self._progress_total = total
            extra = evt.get("extra", {})
            binding = extra.get("binding")
            if binding is not None:
                self._hit_count = max(self._hit_count, int(binding))
            progress.set_progress(done, self._progress_info())
        elif etype == "hit":
            prob = evt.get("probability", 0.0)
            self._best_probability = (
                prob
                if self._best_probability is None
                else max(self._best_probability, prob)
            )
            hit_index = self._hit_index(evt)
            if hit_index is None:
                self._hit_count += 1
            else:
                self._hit_count = max(self._hit_count, hit_index)
            progress.set_progress(self._progress_done, self._progress_info())

    def _progress_info(self) -> str:
        parts = [f"Progress: {self._progress_done:,}/{self._progress_total:,}"]
        parts.append(f"Hits: {self._hit_count:,}")
        if self._best_probability is not None:
            parts.append(f"Best P: {self._best_probability:.4f}")
        return " | ".join(parts)

    def _hit_index(self, evt: dict) -> int | None:
        candidate_id = str(evt.get("candidate_id", ""))
        match = re.fullmatch(r"hit_(\d+)", candidate_id)
        if match:
            return int(match.group(1))
        return None

    def _on_job_done(self, summary: dict, progress: ProgressBubble) -> None:
        # Reload state (the job runner saves it)
        state = self.screen.app.current_state
        self.screen.app.reload_current_state(state.run_id)
        state = self.screen.app.current_state

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

        ns = next_step(Step.CANDIDATE_ENUMERATION)
        if ns:
            self.screen.advance_to_step(ns)

    def _on_job_error(self, msg: str) -> None:
        self.screen.add_system_message(f"Enumeration failed: {msg}", "error-text")
        self.screen.set_input_enabled(True)

    def _create_progress_bubble(self, total_space: int) -> ProgressBubble:
        progress = ProgressBubble(total_space, label="Enumerating & Scoring")
        self.screen.add_structured_widget(progress)
        return progress

    def _show_preview(self, candidates, predictions) -> None:
        preview = []
        for candidate, pred in zip(candidates[:10], predictions[:10]):
            label_str = "Bind" if pred.label == 1 else "Non-bind"
            mut_str = ", ".join(
                f"{m.position}:{m.original}>{m.mutated}"
                for m in candidate.mutations
            )
            preview.append(
                f"  {candidate.candidate_id}: {label_str} P={pred.probability:.4f} | {mut_str}"
            )
        if len(candidates) > 10:
            preview.append(f"  ... and {len(candidates) - 10} more")
        if preview:
            self.screen.add_system_message("\n".join(preview))

    def _rewind_after_empty_result(
        self,
        state: Any,
        total: int,
        hits: int,
        kept: int,
    ) -> None:
        recovery = prepare_empty_candidate_recovery(
            state,
            total=total,
            hits=hits,
            kept=kept,
        )
        self.screen.app.save_state()

        if recovery.needs_regeneration:
            self.screen.add_system_message(
                "No binding candidates were found for the selected LLM plan. "
                "Returning to site proposal with this feedback so the LLM can revise the sites.",
                "warning-text",
            )
        else:
            self.screen.add_system_message(
                "No binding candidates were found for the selected sites. "
                "Returning to site proposal so you can choose a different set. "
                "You can also use /resume to open another saved run or /quit to exit.",
            )
        self.screen.rewind_to_step(
            Step.SITE_PROPOSAL,
            metadata={"reason": "no_positive_candidates"},
        )
