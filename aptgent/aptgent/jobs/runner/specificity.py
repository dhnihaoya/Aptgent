"""Specificity job runner: cross-predict candidates against analog molecules."""
from __future__ import annotations

import json
import logging
import threading
from typing import Any

from aptgent.bootstrap.config import load_config
from aptgent.jobs.cancel import CancelContext
from aptgent.jobs.events import EventWriter
from aptgent.jobs.resume import iter_result_lines, open_artifact, read_jsonl_header, validate_meta
from aptgent.workflow.persistence import Persistence

_log = logging.getLogger(__name__)


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
    selected_ids = set(state.affinity_selected_ids) if state.affinity_selected_ids else set()
    if selected_ids:
        candidates = [c for c in candidates if c.candidate_id in selected_ids]
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
    if validate_meta(results_path, meta):
        for entry in iter_result_lines(results_path):
            cid = entry.get("candidate_id", "")
            if cid:
                done_status[cid] = entry
    elif results_path.exists() and results_path.stat().st_size > 0:
        results_path.unlink(missing_ok=True)

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
    artifact_lock = threading.Lock()
    file_handle: Any = None

    cmd_file = persistence.job_cmd_file(state.run_id, "specificity_filter")

    with CancelContext(cmd_file) as cancel_ctx:
        cancel_event = cancel_ctx.cancel_event

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
                file_handle, _is_fresh = open_artifact(results_path, meta=meta)
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
            if file_handle is not None:
                file_handle.close()

    if cancel_ctx.cancelled:
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
    results_path,
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
