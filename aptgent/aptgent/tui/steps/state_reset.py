from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from aptgent.tui.steps.job_mixin import is_job_alive
from aptgent.workflow.persistence import Persistence
from aptgent.workflow.state import (
    DockingRecommendationContext,
    SpecificityRecommendationContext,
)


def reset_after_site_selection(state: Any, persistence: Persistence) -> None:
    """Clear candidate-derived state when mutation sites are changed."""
    _reset_candidate_outputs(state)
    _clear_job_state(state.run_id, "candidate_enumeration", persistence)
    _clear_job_state(state.run_id, "docking_run", persistence)
    _unlink(persistence.run_dir(state.run_id) / "artifacts" / "scored_candidates.jsonl")
    _rmtree(persistence.run_dir(state.run_id) / "docking")


def _reset_candidate_outputs(state: Any) -> None:
    state.candidates = []
    state.predictions = []
    state.specificity_results = []
    state.docking_plan = None
    state.docking_results = []
    state.spatial_ranks = []
    state.recommendations = []
    state.context.specificity_recommendation = SpecificityRecommendationContext()
    state.context.docking_recommendation = DockingRecommendationContext()


def _clear_job_state(run_id: str, step: str, persistence: Persistence) -> None:
    if is_job_alive(persistence, run_id, step):
        raise RuntimeError(
            f"Cannot change mutation sites while {step} job is still running."
        )

    for path in (
        persistence.job_pid_file(run_id, step),
        persistence.job_events_file(run_id, step),
        persistence.job_cmd_file(run_id, step),
        persistence.job_status_file(run_id, step),
    ):
        _unlink(path)


def _unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _rmtree(path: Path) -> None:
    try:
        shutil.rmtree(path)
    except FileNotFoundError:
        pass
    except OSError:
        pass
