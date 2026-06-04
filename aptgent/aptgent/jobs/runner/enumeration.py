"""Enumeration job runner: mutation-batch prediction with top-K selection."""
from __future__ import annotations

import heapq
import json
import logging
from pathlib import Path
from typing import Any

from aptgent.bootstrap.config import load_config
from aptgent.jobs.cancel import CancelContext
from aptgent.jobs.events import EventWriter
from aptgent.jobs.resume import iter_result_lines, read_jsonl_header
from aptgent.workflow.context import get_sequence
from aptgent.workflow.persistence import Persistence

_log = logging.getLogger(__name__)


def _run_enumeration(writer: EventWriter, state: Any, persistence: Persistence) -> None:
    from aptgent.bootstrap.container import create_prediction_adapter
    from aptgent.domain.models import CandidateSequence, Mutation, PredictionResult
    from aptgent.domain.ranking import ProbHistogramRanker

    bundle = load_config()
    tools_config = bundle.tools
    enum_cfg = bundle.workflow.get("enumeration", {})

    seq: str = get_sequence(state) or ""
    sites = state.confirmed_mutation_sites
    if not sites:
        raise RuntimeError("No mutation sites configured")

    target = state.target_molecule
    if not target or not target.smiles:
        raise RuntimeError("Target molecule/SMILES missing")

    top_k_keep = enum_cfg.get("top_k_keep", 500)
    sub_batch_size = enum_cfg.get("sub_batch_size", 65536)
    progress_every = enum_cfg.get("progress_every", 10000)
    timeout_seconds = enum_cfg.get("mutation_batch_timeout_seconds", 3600)
    if timeout_seconds <= 0:
        timeout_seconds = None

    num_models = enum_cfg.get("num_models", 9)
    total_space = 4 ** len(sites)

    run_dir = persistence.run_dir(state.run_id)
    artifact_dir = run_dir / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    results_path = artifact_dir / "scored_candidates.jsonl"

    # --- Resume: rebuild histograms from existing results ---
    skip_first = 0
    total_binding = 0
    ranker = ProbHistogramRanker(num_models=num_models)
    run_meta = {"base_sequence": seq, "sites": sites, "total_space": total_space}

    header = read_jsonl_header(results_path)
    stored_meta = header.get("meta") if header else None
    if stored_meta and stored_meta.get("base_sequence") == seq and stored_meta.get("sites") == sites:
        for entry in iter_result_lines(results_path):
            skip_first += 1
            pred = entry.get("prediction", {})
            if pred.get("label") == 1:
                total_binding += 1
                model_probs = pred.get("model_probabilities", [])
                if len(model_probs) == num_models:
                    ranker.add(model_probs)

    if skip_first >= total_space:
        writer.write_progress(done=total_space, total=total_space, extra={"binding": total_binding})
        _finalize_enumeration(
            writer, state, persistence, seq, sites, target,
            ranker, top_k_keep, total_space, total_binding, results_path,
            num_models,
        )
        return

    writer.write_progress(
        done=skip_first, total=total_space,
        extra={"binding": total_binding, "resumed": skip_first > 0},
    )

    if skip_first > 0:
        file_handle = open(results_path, "a", encoding="utf-8")
    else:
        file_handle = open(results_path, "w", encoding="utf-8")
        file_handle.write(json.dumps({"meta": run_meta}, ensure_ascii=False) + "\n")

    adapter_summary: dict[str, Any] = {}
    cmd_file = persistence.job_cmd_file(state.run_id, "candidate_enumeration")

    with CancelContext(cmd_file) as cancel_ctx:
        cancel_event = cancel_ctx.cancel_event
        try:
            adapter = create_prediction_adapter(tools_config)
            if not hasattr(adapter, "predict_mutation_batch"):
                raise RuntimeError("Prediction adapter does not support predict_mutation_batch")

            def _on_progress(done: int, total: int, info: dict) -> None:
                writer.write_progress(done=done, total=total, extra={"binding": total_binding})

            def _on_result(result: dict) -> None:
                nonlocal total_binding
                total_binding += 1

                prob = result.get("probability", 0.0)
                model_probs = result.get("model_probabilities", [])
                entry = {
                    "candidate": {"sequence": result["sequence"]},
                    "prediction": {
                        "label": 1,
                        "probability": prob,
                        "model_probabilities": model_probs,
                    },
                }
                file_handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

                if len(model_probs) == num_models:
                    ranker.add(model_probs)

                if total_binding <= 20 or total_binding % 200 == 0:
                    writer.write_hit(
                        candidate_id=f"hit_{total_binding}",
                        probability=prob,
                        extra={"sequence": result["sequence"]},
                    )

            result_summary = adapter.predict_mutation_batch(
                base_sequence=seq,
                target=target,
                sites=sites,
                progress_callback=_on_progress,
                result_callback=_on_result,
                progress_every=progress_every,
                cancel_event=cancel_event,
                timeout_seconds=timeout_seconds,
                skip_first=skip_first,
                sub_batch_size=sub_batch_size,
            )
            if isinstance(result_summary, dict):
                adapter_summary = result_summary
            file_handle.flush()
        except Exception as exc:
            raise RuntimeError(f"Enumeration failed: {exc}") from exc
        finally:
            file_handle.close()

    if cancel_ctx.cancelled or adapter_summary.get("cancelled"):
        writer.write_done(summary={"cancelled": True, "hits": total_binding})
        return

    _finalize_enumeration(
        writer, state, persistence, seq, sites, target,
        ranker, top_k_keep, total_space, total_binding, results_path,
        num_models,
    )


def _finalize_enumeration(
    writer: EventWriter,
    state: Any,
    persistence: Persistence,
    seq: str,
    sites: list[int],
    target: Any,
    ranker: Any,
    top_k_keep: int,
    total_space: int,
    total_binding: int,
    results_path: Path,
    num_models: int,
) -> None:
    from aptgent.domain.models import CandidateSequence, Mutation, PredictionResult

    ranker.finalize()

    # Rescan jsonl to compute rank_sum for each candidate and keep top-K.
    # Max-heap by rank_sum (negate for max-heap via heapq min-heap).
    # Tiebreak: average probability descending (negate for consistent ordering).
    top_heap: list[tuple[int, float, str, list[float]]] = []  # (rank_sum, -avg_prob, seq, model_probs)
    skipped_count = 0

    for entry in iter_result_lines(results_path):
        pred = entry.get("prediction", {})
        if pred.get("label") != 1:
            continue
        model_probs = pred.get("model_probabilities", [])
        if len(model_probs) != num_models:
            skipped_count += 1
            continue
        candidate_seq = entry["candidate"]["sequence"]
        rs = ranker.rank_sum(model_probs)
        avg_prob = sum(model_probs) / num_models

        item = (rs, -avg_prob, candidate_seq, model_probs)
        if len(top_heap) < top_k_keep:
            heapq.heappush(top_heap, item)
        elif item < top_heap[0]:
            heapq.heapreplace(top_heap, item)

    # Sort ascending by rank_sum, then descending by average probability.
    top_heap.sort()

    top_candidates: list[CandidateSequence] = []
    top_predictions: list[PredictionResult] = []

    for rank, (rs, neg_avg, candidate_seq, model_probs) in enumerate(top_heap):
        avg_prob = -neg_avg
        muts = _diff_mutations(seq, candidate_seq, sites)
        cumulative_rank = rank + 1
        cand = CandidateSequence(
            sequence=candidate_seq,
            mutations=muts,
            edit_ratio=len(muts) / len(seq) if seq else 0.0,
            candidate_id=f"cand_{rank}",
        )
        top_candidates.append(cand)
        top_predictions.append(
            PredictionResult(
                candidate_id=cand.candidate_id,
                model_name="ensemble",
                target=target.smiles or "",
                score=avg_prob,
                label=1,
                probability=avg_prob,
                raw_outputs={
                    "model_probabilities": model_probs,
                    "rank_sum": rs,
                    "cumulative_rank": cumulative_rank,
                },
            )
        )

    state.candidates = top_candidates
    if top_predictions:
        state.predictions = top_predictions
    persistence.save(state)

    summary: dict[str, Any] = {
        "total": total_space,
        "hits": total_binding,
        "kept": len(top_candidates),
        "skipped_mismatched_models": skipped_count,
        "results_path": str(results_path),
    }
    writer.write_done(summary=summary)


def _diff_mutations(original: str, mutant: str, sites: list[int]) -> list[Any]:
    from aptgent.domain.models import Mutation
    muts: list[Mutation] = []
    for pos in sites:
        if pos < len(mutant) and original[pos] != mutant[pos]:
            muts.append(Mutation(position=pos, original=original[pos], mutated=mutant[pos]))
    return muts
