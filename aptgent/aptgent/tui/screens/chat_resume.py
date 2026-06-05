from __future__ import annotations

from typing import Any

from aptgent.domain.enums import Step
from aptgent.tui.steps.factory import detached_job_step_name
from aptgent.tui.steps.job_mixin import is_job_alive


def detect_resume_target(screen: Any, state: Any) -> Step | None:
    """Return the active detached-job step a resumed chat should attach to."""
    persistence = screen.app.persistence
    run_id = state.run_id
    current = state.current_step

    if current in (
        Step.CANDIDATE_ENUMERATION,
        Step.PRIMARY_SCORING,
        Step.DOCKING_SELECTION,
        Step.DOCKING_RUN,
        Step.SPECIFICITY_FILTER,
        Step.SPATIAL_RANK,
        Step.FINAL_REPORT,
    ):
        step_name = detached_job_step_name(Step.CANDIDATE_ENUMERATION)
        if step_name and is_job_alive(persistence, run_id, step_name):
            screen.add_system_message("Enumeration job is still running, attaching...")
            return Step.CANDIDATE_ENUMERATION

    if current in (
        Step.DOCKING_RUN,
        Step.SPECIFICITY_FILTER,
        Step.SPATIAL_RANK,
        Step.FINAL_REPORT,
    ):
        step_name = detached_job_step_name(Step.DOCKING_RUN)
        if step_name and is_job_alive(persistence, run_id, step_name):
            screen.add_system_message("Docking job is still running, attaching...")
            return Step.DOCKING_RUN

    if current in (Step.SPECIFICITY_FILTER, Step.SPATIAL_RANK, Step.FINAL_REPORT):
        step_name = detached_job_step_name(Step.SPECIFICITY_FILTER)
        if step_name and is_job_alive(persistence, run_id, step_name):
            screen.add_system_message("Specificity job is still running, attaching...")
            return Step.SPECIFICITY_FILTER

    return None
