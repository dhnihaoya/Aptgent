# aptgent/aptgent/jobs/runner.py
"""Detached job runners: ``python -m aptgent run-job <run_id> <step>``.

Each runner loads RunState from the persistence layer, executes the
step logic in an isolated process, and writes events to
runs/<id>/jobs/<step>/events.jsonl.
"""
from __future__ import annotations

import argparse
import atexit
import json
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any, Callable

from aptgent.bootstrap.config import load_config
from aptgent.jobs.events import EventWriter
from aptgent.jobs.pid import clear_pid, read_pid, write_pid
from aptgent.protocol.cancel import CmdFileCancelPoller
from aptgent.workflow.persistence import Persistence

_log = logging.getLogger(__name__)

_HEARTBEAT_INTERVAL = 10


def _build_persistence() -> Persistence:
    bundle = load_config()
    return Persistence(bundle.workflow.get("paths", {}).get("runs_dir", "./runs"))


def _write_heartbeat_loop(writer: EventWriter, stop: threading.Event) -> None:
    while not stop.is_set():
        stop.wait(_HEARTBEAT_INTERVAL)
        if not stop.is_set():
            try:
                writer.write_heartbeat()
            except Exception:
                pass


def _run_with_heartbeat(
    run_id: str,
    step: str,
    persistence: Persistence,
    body: Callable[[EventWriter, Any, Persistence], None],
) -> int:
    pid_file = persistence.job_pid_file(run_id, step)
    events_file = persistence.job_events_file(run_id, step)
    cmd_file = persistence.job_cmd_file(run_id, step)
    status_file = persistence.job_status_file(run_id, step)

    # Clear stale cancel commands
    try:
        cmd_file.unlink(missing_ok=True)
    except OSError:
        pass

    write_pid(pid_file, os.getpid())
    atexit.register(clear_pid, pid_file)

    try:
        status_file.write_text("running")
        atexit.register(lambda: status_file.unlink(missing_ok=True))
    except OSError:
        pass

    writer = EventWriter(events_file)
    writer.write_started(pid=os.getpid())

    stop_heartbeat = threading.Event()
    heartbeat_thread = threading.Thread(
        target=_write_heartbeat_loop, args=(writer, stop_heartbeat), daemon=True
    )
    heartbeat_thread.start()

    try:
        state = persistence.load(run_id)
        if state is None:
            writer.write_error(message=f"Run state not found: {run_id}")
            return 1

        body(writer, state, persistence)
        return 0
    except Exception as exc:
        _log.exception("Job runner failed")
        try:
            writer.write_error(message=str(exc))
        except Exception:
            pass
        return 1
    finally:
        stop_heartbeat.set()
        heartbeat_thread.join(timeout=2)
        writer.close()


# ---------------------------------------------------------------------------
# Enumeration job runner
# ---------------------------------------------------------------------------

def _run_enumeration(writer: EventWriter, state: Any, persistence: Persistence) -> None:
    import heapq

    from aptgent.bootstrap.container import create_prediction_adapter
    from aptgent.domain.models import CandidateSequence, Mutation, PredictionResult
    from aptgent.workflow.context import get_sequence

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

    total_space = 4 ** len(sites)

    run_dir = persistence.run_dir(state.run_id)
    artifact_dir = run_dir / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    results_path = artifact_dir / "scored_candidates.jsonl"

    # --- Resume: load existing results ---
    skip_first = 0
    top_heap: list[tuple[float, int, dict]] = []
    heap_counter = 0
    total_binding = 0
    run_meta = {"base_sequence": seq, "sites": sites, "total_space": total_space}

    if results_path.exists() and results_path.stat().st_size > 0:
        try:
            with open(results_path, "r", encoding="utf-8") as rf:
                first_line = rf.readline().strip()
                if first_line:
                    header = json.loads(first_line)
                    stored_meta = header.get("meta")
                    if stored_meta and (
                        stored_meta.get("base_sequence") != seq
                        or stored_meta.get("sites") != sites
                    ):
                        skip_first = 0
                        top_heap.clear()
                    elif stored_meta:
                        for line in rf:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                entry = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            skip_first += 1
                            pred = entry.get("prediction", {})
                            if pred.get("label") == 1:
                                total_binding += 1
                                heap_counter += 1
                                prob = pred.get("probability", 0.0)
                                result_dict = {
                                    "sequence": entry["candidate"]["sequence"],
                                    "probability": prob,
                                    "model_probabilities": pred.get("model_probabilities", []),
                                }
                                if len(top_heap) < top_k_keep:
                                    heapq.heappush(top_heap, (prob, heap_counter, result_dict))
                                elif prob > top_heap[0][0]:
                                    heapq.heapreplace(top_heap, (prob, heap_counter, result_dict))
        except OSError:
            skip_first = 0
            top_heap.clear()
            heap_counter = 0
            total_binding = 0

    if skip_first >= total_space:
        writer.write_progress(done=total_space, total=total_space, extra={"binding": total_binding})
        _finalize_enumeration(
            writer, state, persistence, seq, sites, target,
            top_heap, top_k_keep, total_space, total_binding, results_path,
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

    cancel_event = threading.Event()
    stop_cancel_poller = threading.Event()
    cmd_file = persistence.job_cmd_file(state.run_id, "candidate_enumeration")

    cancel_poller = CmdFileCancelPoller(cmd_file, cancel_event, stop_cancel_poller)
    adapter_summary: dict[str, Any] = {}

    try:
        adapter = create_prediction_adapter(tools_config)
        if not hasattr(adapter, "predict_mutation_batch"):
            raise RuntimeError("Prediction adapter does not support predict_mutation_batch")

        def _on_progress(done: int, total: int, info: dict) -> None:
            writer.write_progress(done=done, total=total, extra={"binding": total_binding})

        def _on_result(result: dict) -> None:
            nonlocal total_binding, heap_counter
            total_binding += 1
            heap_counter += 1

            prob = result.get("probability", 0.0)
            entry = {
                "candidate": {"sequence": result["sequence"]},
                "prediction": {
                    "label": 1,
                    "probability": prob,
                    "model_probabilities": result.get("model_probabilities", []),
                },
            }
            file_handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

            if len(top_heap) < top_k_keep:
                heapq.heappush(top_heap, (prob, heap_counter, result))
            elif prob > top_heap[0][0]:
                heapq.heapreplace(top_heap, (prob, heap_counter, result))

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
        stop_cancel_poller.set()
        cancel_poller.join(timeout=2)
        file_handle.close()

    if cancel_event.is_set() or adapter_summary.get("cancelled"):
        writer.write_done(summary={"cancelled": True, "hits": total_binding})
        return

    _finalize_enumeration(
        writer, state, persistence, seq, sites, target,
        top_heap, top_k_keep, total_space, total_binding, results_path,
    )


def _finalize_enumeration(
    writer: EventWriter,
    state: Any,
    persistence: Persistence,
    seq: str,
    sites: list[int],
    target: Any,
    top_heap: list[tuple[float, int, dict]],
    top_k_keep: int,
    total_space: int,
    total_binding: int,
    results_path: Path,
) -> None:
    from aptgent.domain.models import CandidateSequence, Mutation, PredictionResult

    top_heap.sort(key=lambda item: item[0], reverse=True)
    top_candidates: list[CandidateSequence] = []
    top_predictions: list[PredictionResult] = []

    for rank, (prob, _cnt, result) in enumerate(top_heap):
        mutant_seq = result["sequence"]
        muts = _diff_mutations(seq, mutant_seq, sites)
        cand = CandidateSequence(
            sequence=mutant_seq,
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
                score=prob,
                label=1,
                probability=prob,
                raw_outputs={"model_probabilities": result.get("model_probabilities", [])},
            )
        )

    state.candidates = top_candidates
    if top_predictions:
        state.predictions = top_predictions
    persistence.save(state)

    writer.write_done(
        summary={
            "total": total_space,
            "hits": total_binding,
            "kept": len(top_candidates),
            "results_path": str(results_path),
        }
    )


def _diff_mutations(original: str, mutant: str, sites: list[int]) -> list[Any]:
    from aptgent.domain.models import Mutation
    muts: list[Mutation] = []
    for pos in sites:
        if pos < len(mutant) and original[pos] != mutant[pos]:
            muts.append(Mutation(position=pos, original=original[pos], mutated=mutant[pos]))
    return muts


# ---------------------------------------------------------------------------
# Specificity job runner
# ---------------------------------------------------------------------------

def _run_specificity(writer: EventWriter, state: Any, persistence: Persistence) -> None:
    """Cross-predict candidates against analogs via the streaming CLI.

    Streams `(candidate, target)` rows from the predictor subprocess, writes
    a resume-friendly `specificity_results.jsonl` artifact, and emits
    progress/hit events to the TUI through ``events.jsonl``.
    """
    from aptgent.bootstrap.container import create_prediction_adapter
    from aptgent.domain.models import SpecificityResult

    bundle = load_config()
    tools_config = bundle.tools

    candidates = list(state.candidates)
    target = state.target_molecule
    analogs = list(state.analogs)

    if not candidates:
        raise RuntimeError("No candidates available for specificity filter")
    if not target or not target.smiles:
        raise RuntimeError("Target molecule/SMILES missing")

    valid_analogs = [a for a in analogs if a.smiles]
    if not valid_analogs:
        # No analogs with SMILES -> nothing to cross-screen against; mark all kept.
        results = [
            SpecificityResult(candidate_id=c.candidate_id or "", status="kept")
            for c in candidates
        ]
        state.specificity_results = results
        persistence.save(state)
        writer.write_progress(done=0, total=0, extra={"kept": len(results), "removed": 0})
        writer.write_done(
            summary={
                "total": 0,
                "kept": len(results),
                "removed": 0,
                "results_path": "",
            }
        )
        return

    all_targets = [target] + valid_analogs

    artifact_dir = persistence.get_artifact_dir(state.run_id)
    results_path = artifact_dir / "specificity_results.jsonl"

    target_names = [t.resolved_name or t.input_text or "" for t in all_targets]
    meta = {
        "candidate_ids": [c.candidate_id or "" for c in candidates],
        "target_names": target_names,
        "target_smiles": [t.smiles or "" for t in all_targets],
    }

    # --- Resume detection ---
    done_status: dict[str, dict[str, Any]] = {}
    skip_pairs: list[tuple[int, str]] = []
    if results_path.exists() and results_path.stat().st_size > 0:
        try:
            with open(results_path, "r", encoding="utf-8") as rf:
                first_line = rf.readline().strip()
                if first_line:
                    header = json.loads(first_line)
                    stored_meta = header.get("meta")
                    if stored_meta == meta:
                        for line in rf:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                entry = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            cid = entry.get("candidate_id", "")
                            if cid:
                                done_status[cid] = entry
                    else:
                        results_path.unlink(missing_ok=True)
        except OSError:
            done_status.clear()

    for cid, entry in done_status.items():
        for target_idx in range(len(all_targets)):
            skip_pairs.append((target_idx, cid))

    # Track per-candidate accumulated failures across analogs (target_idx 0 is
    # the primary target, which doesn't count as a 'failed analog').
    pending: dict[str, dict[str, Any]] = {}
    for c in candidates:
        cid = c.candidate_id or ""
        if not cid or cid in done_status:
            continue
        pending[cid] = {"failed_analogs": [], "remaining": len(all_targets)}

    total_pairs = len(candidates) * len(all_targets)
    kept_count = sum(1 for e in done_status.values() if e.get("status") == "kept")
    removed_count = sum(1 for e in done_status.values() if e.get("status") == "removed")

    if not pending:
        # Everything is already done.
        _finalize_specificity(
            writer, state, persistence, candidates, done_status,
            total_pairs, results_path,
        )
        return

    # Open artifact for appending (or fresh write with meta header).
    file_handle = None
    artifact_lock = threading.Lock()

    cancel_event = threading.Event()
    stop_cancel_poller = threading.Event()
    cmd_file = persistence.job_cmd_file(state.run_id, "specificity_filter")

    cancel_poller = CmdFileCancelPoller(cmd_file, cancel_event, stop_cancel_poller)

    current_target_name: str = target_names[0] if target_names else ""
    initial_done = len(done_status) * len(all_targets)
    last_progress_done = initial_done

    def _on_progress(done: int, total: int, info: dict) -> None:
        nonlocal current_target_name, last_progress_done
        # The subprocess reports rows it actually ran; add the skipped baseline
        # so the user sees the true completed-pair count.
        adjusted_done = min(total_pairs, done + initial_done)
        last_progress_done = adjusted_done
        if "target_name" in info:
            current_target_name = str(info["target_name"] or "")
        writer.write_progress(
            done=adjusted_done,
            total=total_pairs,
            extra={
                "kept": kept_count,
                "removed": removed_count,
                "current_target": current_target_name,
            },
        )

    def _on_row(row: dict) -> None:
        nonlocal kept_count, removed_count, current_target_name
        target_idx = int(row.get("target_idx", 0))
        target_name = str(row.get("target_name", "") or "")
        cand_id = str(row.get("candidate_id", "") or "")
        label = int(row.get("label", 0))
        if target_name:
            current_target_name = target_name
        if cand_id not in pending:
            return
        bucket = pending[cand_id]
        if target_idx > 0 and label == 1:
            # Index 0 is the primary target; non-zero indices are analogs.
            bucket["failed_analogs"].append(
                target_names[target_idx]
                if 0 <= target_idx < len(target_names)
                else target_name
            )
        bucket["remaining"] -= 1
        if bucket["remaining"] > 0:
            return

        failed = bucket["failed_analogs"]
        status_str = "removed" if failed else "kept"
        entry = {
            "candidate_id": cand_id,
            "status": status_str,
            "failed_analogs": failed,
        }
        done_status[cand_id] = entry
        with artifact_lock:
            file_handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
            file_handle.flush()
        if status_str == "kept":
            kept_count += 1
        else:
            removed_count += 1
        writer.write_hit(
            candidate_id=cand_id,
            probability=0.0,
            extra={"status": status_str, "failed_analogs": failed},
        )
        pending.pop(cand_id, None)

    try:
        try:
            if results_path.exists() and results_path.stat().st_size > 0:
                file_handle = open(results_path, "a", encoding="utf-8")
            else:
                file_handle = open(results_path, "w", encoding="utf-8")
                file_handle.write(json.dumps({"meta": meta}, ensure_ascii=False) + "\n")
                file_handle.flush()
        except OSError as exc:
            raise RuntimeError(f"Cannot open specificity artifact: {exc}") from exc

        adapter = create_prediction_adapter(tools_config)
        if not hasattr(adapter, "predict_specificity_batch"):
            raise RuntimeError("Prediction adapter does not support predict_specificity_batch")

        adapter.predict_specificity_batch(
            candidates=candidates,
            targets=all_targets,
            progress_callback=_on_progress,
            row_callback=_on_row,
            cancel_event=cancel_event,
            timeout_seconds=None,
            progress_every=1,
            skip_pairs=skip_pairs or None,
        )
    except Exception as exc:
        raise RuntimeError(f"Specificity filter failed: {exc}") from exc
    finally:
        stop_cancel_poller.set()
        cancel_poller.join(timeout=2)
        if file_handle is not None:
            file_handle.close()

    if cancel_event.is_set():
        writer.write_done(
            summary={
                "cancelled": True,
                "total": total_pairs,
                "kept": kept_count,
                "removed": removed_count,
                "results_path": str(results_path),
            }
        )
        return

    _finalize_specificity(
        writer, state, persistence, candidates, done_status,
        total_pairs, results_path,
    )


def _finalize_specificity(
    writer: EventWriter,
    state: Any,
    persistence: Persistence,
    candidates: list[Any],
    done_status: dict[str, dict[str, Any]],
    total_pairs: int,
    results_path: Path,
) -> None:
    from aptgent.domain.models import SpecificityResult

    specificity_results: list[SpecificityResult] = []
    kept = 0
    removed = 0
    for cand in candidates:
        cid = cand.candidate_id or ""
        entry = done_status.get(cid)
        if entry is None:
            # Candidates we never reached (shouldn't happen after a clean run);
            # mark them as pending so callers can detect partial completion.
            specificity_results.append(
                SpecificityResult(candidate_id=cid, status="pending")
            )
            continue
        status_str = entry.get("status", "pending")
        failed = list(entry.get("failed_analogs", []))
        if status_str == "kept":
            kept += 1
        elif status_str == "removed":
            removed += 1
        specificity_results.append(
            SpecificityResult(
                candidate_id=cid,
                status=status_str,
                failed_analogs=failed,
            )
        )

    state.specificity_results = specificity_results
    persistence.save(state)

    writer.write_done(
        summary={
            "total": total_pairs,
            "kept": kept,
            "removed": removed,
            "candidates": len(candidates),
            "results_path": str(results_path),
        }
    )


# ---------------------------------------------------------------------------
# Docking job runner
# ---------------------------------------------------------------------------

def _run_docking(writer: EventWriter, state: Any, persistence: Persistence) -> None:
    import re

    from aptgent.adapters.docking import VinaAdapter
    from aptgent.bootstrap.container import create_vina_adapter
    from aptgent.domain.models import DockingResult

    bundle = load_config()
    tools_config = bundle.tools
    docking_cfg = bundle.workflow.get("docking", {})

    plan = state.docking_plan
    target = state.target_molecule

    if not plan or plan.recommended_top_k <= 0:
        state.docking_results = []
        persistence.save(state)
        writer.write_done(summary={"skipped": True, "reason": "no plan or top_k=0"})
        return

    if not target or not target.smiles:
        raise RuntimeError("Target molecule/SMILES missing")

    ens_preds = [p for p in state.predictions if p.model_name == "ensemble"]
    sorted_preds = sorted(ens_preds, key=lambda item: item.probability or 0.0, reverse=True)
    top_k = plan.recommended_top_k
    top_cand_ids = {pred.candidate_id for pred in sorted_preds[:top_k]}
    top_candidates = [
        c for c in state.candidates if c.candidate_id in top_cand_ids
    ]

    work_dir = persistence.run_dir(state.run_id) / "docking"
    work_dir.mkdir(parents=True, exist_ok=True)

    seed = plan.seed
    if seed is None:
        cfg_seed = docking_cfg.get("seed")
        seed = cfg_seed if cfg_seed is not None else None

    config_timeout = docking_cfg.get("per_ligand_timeout_seconds", 1800)
    plan_timeout = getattr(plan, "per_ligand_timeout_seconds", None)
    per_ligand_timeout = plan_timeout if plan_timeout is not None else config_timeout
    exhaustiveness = plan.exhaustiveness

    receptor_paths: dict[str, str] = dict(plan.receptor_paths or {})
    grid_boxes: dict[str, dict[str, list[float]]] = {}
    for cand_id, box in (plan.grid_boxes or {}).items():
        grid_boxes[cand_id] = {
            "center": list(box.center),
            "size": list(box.size),
        }

    existing_results: list[DockingResult] = []
    remaining_candidates = []
    for cand in top_candidates:
        cand_id = cand.candidate_id or ""
        out_path = VinaAdapter.output_path(work_dir, cand_id)
        if out_path.exists() and out_path.stat().st_size > 0:
            dr = _parse_existing_output(out_path, cand_id)
            if dr.status == "completed":
                existing_results.append(dr)
            else:
                remaining_candidates.append(cand)
        else:
            remaining_candidates.append(cand)

    writer.write_progress(
        done=len(existing_results), total=len(top_candidates),
        extra={"resumed": len(existing_results)},
    )

    cancel_event = threading.Event()
    stop_cancel_poller = threading.Event()
    cmd_file = persistence.job_cmd_file(state.run_id, "docking_run")

    cancel_poller = CmdFileCancelPoller(cmd_file, cancel_event, stop_cancel_poller)

    try:
        if remaining_candidates and not cancel_event.is_set():
            adapter = create_vina_adapter(tools_config)
            if exhaustiveness is not None and exhaustiveness != adapter.exhaustiveness:
                adapter = VinaAdapter(
                    executable=adapter.executable,
                    exhaustiveness=exhaustiveness,
                    num_modes=plan.num_modes or adapter.num_modes,
                    energy_range=plan.energy_range or adapter.energy_range,
                    lazy=True,
                )

            for candidate in remaining_candidates:
                if cancel_event.is_set():
                    break
                batch_results = adapter.run_batch(
                    candidates=[candidate],
                    target=target,
                    receptor_paths=receptor_paths,
                    grid_boxes=grid_boxes,
                    work_dir=work_dir,
                    seed=seed,
                    per_ligand_timeout=per_ligand_timeout,
                )
                existing_results.extend(batch_results)
                writer.write_progress(
                    done=len(existing_results), total=len(top_candidates),
                )
                writer.write_hit(
                    candidate_id=candidate.candidate_id,
                    probability=0.0,
                    extra={
                        "docking_score": (
                            batch_results[0].docking_score
                            if batch_results and batch_results[0].docking_score is not None
                            else None
                        ),
                    },
                )
    except Exception as exc:
        raise RuntimeError(f"Docking failed: {exc}") from exc
    finally:
        stop_cancel_poller.set()
        cancel_poller.join(timeout=2)

    state.docking_results = existing_results
    persistence.save(state)

    writer.write_done(
        summary={
            "total": len(top_candidates),
            "completed": len(existing_results),
            "cancelled": cancel_event.is_set(),
        }
    )


def _parse_existing_output(pdbqt_path: Path, candidate_id: str) -> DockingResult:
    import re

    from aptgent.domain.models import DockingResult

    pattern = re.compile(r"^REMARK VINA RESULT:\s+(-?\d+\.?\d*)")
    best_affinity = None
    try:
        with open(pdbqt_path, "r", encoding="utf-8") as f:
            for line in f:
                m = pattern.match(line)
                if m:
                    affinity = float(m.group(1))
                    if best_affinity is None or affinity < best_affinity:
                        best_affinity = affinity
    except Exception:
        pass
    return DockingResult(
        candidate_id=candidate_id,
        docking_score=best_affinity,
        status="completed" if best_affinity is not None else "parse_error",
        raw_outputs={"resumed_from": str(pdbqt_path)},
    )


# ---------------------------------------------------------------------------
# Registry and entry point
# ---------------------------------------------------------------------------

_JOB_RUNNERS: dict[str, Callable[[EventWriter, Any, Persistence], None]] = {
    "candidate_enumeration": _run_enumeration,
    "specificity_filter": _run_specificity,
    "docking_run": _run_docking,
}


def run_job(run_id: str, step: str, *, persistence: Persistence | None = None) -> int:
    """Main entry: load state, dispatch to runner, write events."""
    pers = persistence or _build_persistence()
    runner_fn = _JOB_RUNNERS.get(step)
    if runner_fn is None:
        print(f"Unknown step for detached execution: {step}", file=sys.stderr)
        return 1

    return _run_with_heartbeat(run_id, step, pers, runner_fn)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aptgent",
        description="Aptamer design workflow agent.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_job_parser = sub.add_parser(
        "run-job",
        help="Run a workflow step as a detached job.",
    )
    run_job_parser.add_argument("run_id", help="The run to execute")
    run_job_parser.add_argument("step", help="The step to run")
    run_job_parser.add_argument("--foreground", action="store_true", help="Run in foreground (debug)")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "run-job":
        logging.basicConfig(
            level=logging.DEBUG if getattr(args, "foreground", False) else logging.INFO,
            format="%(asctime)s %(name)s %(levelname)s %(message)s",
        )
        return run_job(args.run_id, args.step)

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
