from __future__ import annotations

import heapq
import itertools
import json
from typing import Any

from aptgent.domain.enums import Step
from aptgent.domain.models import CandidateSequence, Mutation
from aptgent.tui.steps.base import StepHandler
from aptgent.tui.steps.common import next_step
from aptgent.tui.widgets.chat_widgets import ProgressBubble
from aptgent.workflow.context import get_sequence


class EnumerationHandler(StepHandler):
    """Full enumeration + batch prediction + batch JSONL save + in-memory top-K heap."""

    _BASES = ["A", "T", "G", "C"]

    def enter(self) -> None:
        state = self.screen.app.current_state
        seq: str = get_sequence(state) or ""
        sites = state.confirmed_mutation_sites
        enum_cfg = self.screen.app.config.get("enumeration", {})
        batch_size = enum_cfg.get("batch_size", 1000)
        top_k_keep = enum_cfg.get("top_k_keep", 500)

        if not sites:
            self.screen.add_system_message(
                "No mutation sites selected. Please go back.", "error-text"
            )
            self.screen.set_input_enabled(True)
            return

        total_space = 4 ** len(sites)
        total_batches = (total_space + batch_size - 1) // batch_size
        mode_note = (
            "Large search space detected: accelerated runtime path will be used."
            if self._use_accelerated_search(total_space)
            else "Each batch: enumerate -> predict -> save to JSONL"
        )

        self.screen.add_system_message(
            f"Mutation space: 4^{len(sites)} = {total_space:,} candidates\n"
            f"Batch size: {batch_size:,} | Batches: {total_batches:,} | "
            f"Top-K kept: {top_k_keep:,}\n"
            f"{mode_note}"
        )
        self.run_worker(
            lambda: self._pipeline(seq, sites, total_space, batch_size, top_k_keep),
            activity="Enumerating and scoring candidates...",
        )

    def _use_accelerated_search(self, total_space: int) -> bool:
        enum_cfg = self.screen.app.config.get("enumeration", {})
        threshold = int(enum_cfg.get("acceleration_threshold", 1024))
        return total_space >= threshold

    def _pipeline(
        self,
        seq: str,
        sites: list[int],
        total_space: int,
        batch_size: int,
        top_k_keep: int,
    ) -> None:
        from textual.worker import get_current_worker

        worker = get_current_worker()
        state = self.screen.app.current_state
        target = state.target_molecule
        can_score = bool(target and target.smiles)

        run_dir = self.screen.app.persistence._run_dir(state.run_id)
        artifact_dir = run_dir / "artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        results_path = artifact_dir / "scored_candidates.jsonl"

        progress = self.screen.app.call_from_thread(
            self._create_progress_bubble,
            total_space,
        )

        if can_score and self._use_accelerated_search(total_space):
            self._run_accelerated_pipeline(
                seq=seq,
                sites=sites,
                total_space=total_space,
                top_k_keep=top_k_keep,
                results_path=results_path,
                progress=progress,
            )
            return

        top_heap: list[tuple[float, int, CandidateSequence, Any]] = []
        heap_counter = 0
        total_processed = 0
        total_binding = 0
        batch_num = 0
        total_batches = (total_space + batch_size - 1) // batch_size
        batch_buf: list[CandidateSequence] = []

        try:
            with open(results_path, "w", encoding="utf-8") as handle:
                for combo in itertools.product(self._BASES, repeat=len(sites)):
                    if worker.is_cancelled:
                        return

                    cand = self._build_candidate(seq, sites, combo, total_processed)
                    batch_buf.append(cand)
                    total_processed += 1

                    if len(batch_buf) < batch_size and total_processed < total_space:
                        continue

                    batch_num += 1
                    batch_preds: list[Any] = []

                    if can_score:
                        try:
                            batch_preds = self.screen.app.prediction_adapter.predict_batch(
                                batch_buf, target
                            )
                        except Exception as exc:
                            self.screen.app.call_from_thread(
                                self.screen.add_system_message,
                                f"Batch {batch_num} scoring error: {exc}",
                                "warning-text",
                            )

                    for index, candidate in enumerate(batch_buf):
                        entry: dict[str, Any] = {"candidate": candidate.model_dump()}
                        if index < len(batch_preds):
                            pred = batch_preds[index]
                            entry["prediction"] = pred.model_dump()
                            prob = pred.probability or 0.0
                            if pred.label == 1:
                                total_binding += 1
                            heap_counter += 1
                            if len(top_heap) < top_k_keep:
                                heapq.heappush(top_heap, (prob, heap_counter, candidate, pred))
                            elif prob > top_heap[0][0]:
                                heapq.heapreplace(top_heap, (prob, heap_counter, candidate, pred))
                        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

                    handle.flush()

                    info_parts = [f"Batch {batch_num:,}/{total_batches:,}"]
                    if can_score:
                        info_parts.append(f"Binding: {total_binding:,}")
                        if top_heap:
                            best_prob = max(h[0] for h in top_heap)
                            info_parts.append(f"Best: {best_prob:.4f}")
                    self.screen.app.call_from_thread(
                        progress.set_progress,
                        total_processed,
                        " | ".join(info_parts),
                    )
                    batch_buf = []

        except Exception as exc:
            self.screen.app.call_from_thread(
                self.screen.add_system_message,
                f"Pipeline failed at candidate {total_processed:,}: {exc}",
                "error-text",
            )
            self.screen.app.call_from_thread(self.screen.set_input_enabled, True)
            return

        top_heap.sort(key=lambda item: item[0], reverse=True)
        top_candidates = [item[2] for item in top_heap]
        top_predictions = [item[3] for item in top_heap]

        state.candidates = top_candidates
        if top_predictions:
            state.predictions = top_predictions
        self.screen.app.save_state()

        finish_msg = f"Scored {total_processed:,} candidates"
        if can_score:
            finish_msg += f", {total_binding:,} binding, top {len(top_candidates)} kept"
        finish_msg += f"\nResults: {results_path}"
        self.screen.app.call_from_thread(progress.finish, finish_msg)

        preview = []
        for candidate, pred in zip(top_candidates[:10], top_predictions[:10]):
            label_str = "Bind" if pred.label == 1 else "Non-bind"
            mut_str = ", ".join(
                f"{mutation.position}:{mutation.original}>{mutation.mutated}"
                for mutation in candidate.mutations
            )
            preview.append(
                f"  {candidate.candidate_id}: {label_str} P={pred.probability:.4f} | {mut_str}"
            )
        if len(top_candidates) > 10:
            preview.append(f"  ... and {len(top_candidates) - 10} more")
        if preview:
            self.screen.app.call_from_thread(
                self.screen.add_system_message, "\n".join(preview)
            )

        ns = next_step(Step.CANDIDATE_ENUMERATION)
        if ns:
            self.screen.app.call_from_thread(self.screen.advance_to_step, ns)

    def _run_accelerated_pipeline(
        self,
        *,
        seq: str,
        sites: list[int],
        total_space: int,
        top_k_keep: int,
        results_path,
        progress,
    ) -> None:
        state = self.screen.app.current_state
        target = state.target_molecule
        assert target is not None

        try:
            candidates, predictions, metadata = self.screen.app.prediction_adapter.search_mutation_space(
                seq,
                target,
                sites,
                top_k_keep=top_k_keep,
            )
            with open(results_path, "w", encoding="utf-8") as handle:
                for candidate, prediction in zip(candidates, predictions):
                    entry = {
                        "candidate": candidate.model_dump(),
                        "prediction": prediction.model_dump(),
                    }
                    handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

            total_processed = int(metadata.get("total_processed", total_space))
            total_binding = int(metadata.get("binding_hit_count", len(predictions)))
            self.screen.app.call_from_thread(
                progress.set_progress,
                total_processed,
                f"Accelerated search | Binding: {total_binding:,}",
            )
        except Exception as exc:
            self.screen.app.call_from_thread(
                self.screen.add_system_message,
                f"Accelerated enumeration failed: {exc}",
                "error-text",
            )
            self.screen.app.call_from_thread(self.screen.set_input_enabled, True)
            return

        state.candidates = candidates
        if predictions:
            state.predictions = predictions
        self.screen.app.save_state()

        finish_msg = (
            f"Scored {total_processed:,} candidates, {total_binding:,} binding, "
            f"top {len(candidates)} kept\nResults: {results_path}"
        )
        self.screen.app.call_from_thread(progress.finish, finish_msg)

        preview = []
        for candidate, pred in zip(candidates[:10], predictions[:10]):
            label_str = "Bind" if pred.label == 1 else "Non-bind"
            mut_str = ", ".join(
                f"{mutation.position}:{mutation.original}>{mutation.mutated}"
                for mutation in candidate.mutations
            )
            preview.append(
                f"  {candidate.candidate_id}: {label_str} P={pred.probability:.4f} | {mut_str}"
            )
        if len(candidates) > 10:
            preview.append(f"  ... and {len(candidates) - 10} more")
        if preview:
            self.screen.app.call_from_thread(
                self.screen.add_system_message, "\n".join(preview)
            )

        ns = next_step(Step.CANDIDATE_ENUMERATION)
        if ns:
            self.screen.app.call_from_thread(self.screen.advance_to_step, ns)

    def _create_progress_bubble(self, total_space: int) -> ProgressBubble:
        progress = ProgressBubble(total_space, label="Enumerating & Scoring")
        self.screen.add_structured_widget(progress)
        return progress

    @staticmethod
    def _build_candidate(
        seq: str,
        sites: list[int],
        combo: tuple[str, ...],
        index: int,
    ) -> CandidateSequence:
        muts: list[Mutation] = []
        new_seq = list(seq)
        for idx, base in zip(sites, combo):
            muts.append(Mutation(position=idx, original=seq[idx], mutated=base))
            new_seq[idx] = base
        cand_seq = "".join(new_seq)
        edit_ratio = len(muts) / len(seq)
        return CandidateSequence(
            sequence=cand_seq,
            mutations=muts,
            edit_ratio=edit_ratio,
            candidate_id=f"cand_{index}",
        )
