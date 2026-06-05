from __future__ import annotations

from typing import Any

from aptgent.domain.enums import Step
from aptgent.tui.steps.factory import detached_job_step_name
from aptgent.tui.steps.job_mixin import is_job_alive
from aptgent.workflow.engine import STEP_ORDER


def detect_resume_target(screen: Any, state: Any) -> Step | None:
    """Return the active detached-job step a resumed chat should attach to.

    Iterates the canonical step order and returns the earliest step whose
    detached job is still alive and whose position is at-or-before the
    current step.  This avoids hardcoding step-name tuples — adding a new
    detached-job step only requires defining ``JOB_STEP`` on its handler.
    """
    persistence = screen.app.persistence
    run_id = state.run_id
    current = state.current_step

    try:
        current_idx = STEP_ORDER.index(current)
    except ValueError:
        return None

    for idx, step in enumerate(STEP_ORDER):
        if idx > current_idx:
            break
        step_name = detached_job_step_name(step)
        if step_name and is_job_alive(persistence, run_id, step_name):
            label = step_name.replace("_", " ").title()
            screen.add_system_message(f"{label} job is still running, attaching...")
            return step

    return None
