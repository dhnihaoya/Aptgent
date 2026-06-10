"""Docking job runner: AutoDock Vina molecular docking."""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from aptgent.bootstrap.config import load_config
from aptgent.jobs.cancel import CancelContext
from aptgent.jobs.events import EventWriter
from aptgent.workflow.persistence import Persistence

_log = logging.getLogger(__name__)


def _dock_candidate_ids(state: Any, plan: Any) -> list[str]:
    """Return candidate IDs to dock, in ensemble rank order.

    Only IDs present in ``plan.receptor_paths`` are eligible — this matches
    the structure-preparation step (including mutation-ratio filtering and
    partial RNAComposer/MOE success).  ``recommended_top_k`` caps how many
    of those prepared receptors are actually docked.
    """
    receptor_paths: dict[str, str] = dict(plan.receptor_paths or {})
    if not receptor_paths:
        return []

    ens_preds = [p for p in state.predictions if p.model_name == "ensemble"]
    sorted_preds = sorted(
        ens_preds,
        key=lambda item: item.raw_outputs.get("cumulative_rank", float("inf")),
    )

    ranked: list[str] = [
        pred.candidate_id
        for pred in sorted_preds
        if pred.candidate_id in receptor_paths
    ]
    for cand_id in receptor_paths:
        if cand_id not in ranked:
            ranked.append(cand_id)

    top_k = plan.recommended_top_k
    if top_k > 0:
        return ranked[:top_k]
    return ranked


def _run_docking(writer: EventWriter, state: Any, persistence: Persistence) -> None:
    from aptgent.adapters.docking import VinaAdapter
    from aptgent.bootstrap.container import create_vina_adapter
    from aptgent.domain.models import DockingResult

    bundle = load_config()
    tools_config = bundle.tools
    docking_cfg = bundle.workflow.get("docking", {})

    plan = state.docking_plan
    target = state.target_molecule

    if not docking_cfg.get("enabled", True):
        state.docking_results = []
        persistence.save(state)
        writer.write_done(summary={"skipped": True, "reason": "docking disabled in config"})
        return

    if not plan or plan.recommended_top_k <= 0:
        state.docking_results = []
        persistence.save(state)
        writer.write_done(summary={"skipped": True, "reason": "no plan or top_k=0"})
        return

    if not target or not target.smiles:
        raise RuntimeError("Target molecule/SMILES missing")

    receptor_paths: dict[str, str] = dict(plan.receptor_paths or {})
    if not receptor_paths:
        state.docking_results = []
        persistence.save(state)
        writer.write_done(summary={"skipped": True, "reason": "no receptor_paths"})
        return

    dock_ids = _dock_candidate_ids(state, plan)
    id_to_candidate = {c.candidate_id: c for c in state.candidates}
    top_candidates = [id_to_candidate[cid] for cid in dock_ids if cid in id_to_candidate]

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
            dr = _parse_existing_output(out_path, cand_id, receptor_paths.get(cand_id))
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

    cmd_file = persistence.job_cmd_file(state.run_id, "docking_run")

    with CancelContext(cmd_file) as cancel_ctx:
        cancel_event = cancel_ctx.cancel_event
        try:
            if remaining_candidates and not cancel_ctx.cancelled:
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
                    if cancel_ctx.cancelled:
                        break
                    batch_results = adapter.run_batch(
                        candidates=[candidate],
                        target=target,
                        receptor_paths=receptor_paths,
                        grid_boxes=grid_boxes,
                        work_dir=work_dir,
                        seed=seed,
                        per_ligand_timeout=per_ligand_timeout,
                        cancel_event=cancel_ctx.cancel_event,
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

    state.docking_results = existing_results
    persistence.save(state)

    writer.write_done(
        summary={
            "total": len(top_candidates),
            "completed": len(existing_results),
            "cancelled": cancel_ctx.cancelled,
        }
    )


def _parse_existing_output(
    pdbqt_path: Path,
    candidate_id: str,
    receptor_pdbqt: str | None = None,
) -> Any:
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
        _log.warning("Failed to parse PDBQT output: %s", pdbqt_path, exc_info=True)
    raw_outputs: dict[str, Any] = {
        "resumed_from": str(pdbqt_path),
        "output_pdbqt": str(pdbqt_path),
    }
    if receptor_pdbqt:
        raw_outputs["receptor_pdbqt"] = str(receptor_pdbqt)
    return DockingResult(
        candidate_id=candidate_id,
        docking_score=best_affinity,
        status="completed" if best_affinity is not None else "parse_error",
        raw_outputs=raw_outputs,
    )
