"""Module-level helper functions for the docking selection step."""
from __future__ import annotations

import functools
import logging
from typing import Any

from aptgent.bootstrap.config import load_config
from aptgent.domain.models import DockingPlan, GridBox
from aptgent.tui.steps.common import DEFAULT_PER_LIGAND_TIMEOUT_SECONDS

_log = logging.getLogger(__name__)


def _candidate_id(cand: Any, index: int) -> str:
    raw = cand.candidate_id or f"cand_{index}"
    return raw.replace(" ", "_")


def _top_k_bundle(state: Any) -> tuple[int, list[Any]]:
    plan = state.docking_plan
    top_k = (
        (plan.recommended_top_k if plan is not None else None)
        or state.context.docking_recommendation.recommended_top_k
        or 100
    )
    return top_k, list(state.candidates[:top_k])


def _machine_profile(state: Any) -> dict[str, Any]:
    recommendation = state.context.docking_recommendation
    profile = recommendation.machine_profile
    if profile:
        return dict(profile)
    import os
    cpu_count = os.cpu_count() or 1
    mem_bytes = None
    try:
        import psutil
        mem_bytes = psutil.virtual_memory().total
    except Exception:
        pass
    return {
        "cpu_count": cpu_count,
        "memory_bytes": mem_bytes,
        "memory_gb": round(mem_bytes / (1024 ** 3), 2) if mem_bytes else None,
    }


def _per_ligand_timeout_default() -> int:
    """Resolve the per-ligand timeout fallback from workflow.toml."""
    try:
        bundle = load_config()
        return int(
            bundle.workflow.get("docking", {}).get(
                "per_ligand_timeout_seconds",
                DEFAULT_PER_LIGAND_TIMEOUT_SECONDS,
            )
        )
    except Exception:
        _log.debug("Failed to resolve per-ligand timeout default", exc_info=True)
        return DEFAULT_PER_LIGAND_TIMEOUT_SECONDS


@functools.lru_cache(maxsize=1)
def _per_ligand_timeout_default_cached() -> int:
    return _per_ligand_timeout_default()


def _apply_docking_plan(
    state: Any,
    *,
    receptor_paths: dict[str, str],
    grid_boxes: dict[str, dict[str, list[float]]],
    source: str,
    top_k: int,
) -> None:
    recommendation = state.context.docking_recommendation
    plan = state.docking_plan or DockingPlan(
        machine_profile=_machine_profile(state),
        recommended_top_k=top_k,
        exhaustiveness=recommendation.recommended_exhaustiveness or 8,
    )
    plan.receptor_paths = receptor_paths
    plan.grid_boxes = {
        cid: GridBox(center=box["center"], size=box["size"])
        for cid, box in grid_boxes.items()
    }
    plan.receptor_source = source
    plan.recommended_top_k = top_k
    state.docking_plan = plan
    recommendation.phase = "structures_ready"


def _compute_mutation_ratio(candidate: Any, confirmed_sites: list[int]) -> float:
    """Fraction of confirmed_sites that have a mutation in candidate.

    Both Mutation.position and confirmed_sites must be 0-based.
    """
    if not confirmed_sites:
        return 1.0
    mutated_positions = {m.position for m in candidate.mutations}
    return sum(1 for s in confirmed_sites if s in mutated_positions) / len(confirmed_sites)


def _filtered_top_k_bundle(
    state: Any,
    *,
    mutation_ratio: float | None = None,
) -> tuple[int, list[Any]]:
    """Top-k candidates filtered by mutation ratio.

    Returns (filtered_count, filtered_list).
    If mutation_ratio is None or <= 0 or no confirmed sites, returns unfiltered bundle.
    """
    top_k, top_candidates = _top_k_bundle(state)
    if mutation_ratio is None or mutation_ratio <= 0:
        return top_k, top_candidates
    confirmed_sites = state.confirmed_mutation_sites or []
    if not confirmed_sites:
        return top_k, top_candidates
    filtered = [
        c for c in top_candidates
        if _compute_mutation_ratio(c, confirmed_sites) >= mutation_ratio
    ]
    return len(filtered), filtered
