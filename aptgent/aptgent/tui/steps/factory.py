from __future__ import annotations

from typing import Any

from aptgent.domain.enums import Step
from aptgent.tui.steps.base import StepHandler
from aptgent.tui.steps.docking_run import DockingRunHandler
from aptgent.tui.steps.docking_selection import DockingSelectionHandler
from aptgent.tui.steps.enumeration import EnumerationHandler
from aptgent.tui.steps.intake import IntakeHandler
from aptgent.tui.steps.report import ReportHandler
from aptgent.tui.steps.scoring import ScoringHandler
from aptgent.tui.steps.site_proposal import SiteProposalHandler
from aptgent.tui.steps.spatial_rank import SpatialRankHandler
from aptgent.tui.steps.specificity import SpecificityHandler
from aptgent.tui.steps.structure import StructureHandler

_HANDLER_MAP: dict[Step, type[StepHandler]] = {
    Step.INTAKE: IntakeHandler,
    Step.SECONDARY_STRUCTURE: StructureHandler,
    Step.SITE_PROPOSAL: SiteProposalHandler,
    Step.CANDIDATE_ENUMERATION: EnumerationHandler,
    Step.PRIMARY_SCORING: ScoringHandler,
    Step.SPECIFICITY_FILTER: SpecificityHandler,
    Step.DOCKING_SELECTION: DockingSelectionHandler,
    Step.DOCKING_RUN: DockingRunHandler,
    Step.SPATIAL_RANK: SpatialRankHandler,
    Step.FINAL_REPORT: ReportHandler,
}


def create_handler(step: Step, screen: Any) -> StepHandler:
    """Factory: create the appropriate handler for a step."""
    cls = _HANDLER_MAP.get(step)
    if cls is None:
        raise ValueError(f"No handler registered for step: {step}")
    return cls(screen)


def detached_job_step_name(step: Step) -> str | None:
    """Return the detached job runner step owned by a workflow step, if any."""
    cls = _HANDLER_MAP.get(step)
    if cls is None:
        return None
    job_step = getattr(cls, "JOB_STEP", "")
    return job_step or None
