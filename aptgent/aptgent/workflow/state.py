from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field

from aptgent.domain.enums import Status, Step
from aptgent.domain.models import (
    ArtifactRef,
    CandidateSequence,
    DockingPlan,
    DockingResult,
    FinalRecommendation,
    PredictionResult,
    SecondaryStructure,
    SpatialRankResult,
    SpecificityResult,
    TargetMolecule,
)


class IntakeContext(BaseModel):
    user_brief: Optional[str] = None
    sequence: Optional[str] = None
    target_input: Optional[str] = None
    target_label: Optional[str] = None
    modification_region: Optional[str] = None
    analogs: list[str] = Field(default_factory=list)
    time_budget_hours: Optional[int] = None


class SiteProposalContext(BaseModel):
    proposed_sites: list[int] = Field(default_factory=list)
    reasoning: Optional[str] = None
    confidence: Optional[str] = None
    confirmed_sites: list[int] = Field(default_factory=list)


class DockingRecommendationContext(BaseModel):
    candidate_count: int = 0
    machine_profile: dict[str, Any] = Field(default_factory=dict)
    time_budget_hours: Optional[int] = None
    recommended_time_budget_hours: Optional[int] = None
    recommended_top_k: int = 0
    recommended_grid_size: list[float] = Field(default_factory=list)
    receptor_path_note: str = ""
    grid_center_note: str = ""
    reason: str = ""
    display_markdown: str = ""
    strategy: str = ""
    phase: str = "initial"
    accepted: bool = False


class WorkflowContext(BaseModel):
    intake: IntakeContext = Field(default_factory=IntakeContext)
    site_proposal: SiteProposalContext = Field(default_factory=SiteProposalContext)
    docking_recommendation: DockingRecommendationContext = Field(
        default_factory=DockingRecommendationContext
    )


class RunState(BaseModel):
    run_id: str
    current_step: Step = Step.INTAKE
    status: Status = Status.PENDING
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # Inputs & confirmations
    input_payload: dict[str, Any] = Field(default_factory=dict)
    target_molecule: Optional[TargetMolecule] = None
    confirmed_mutation_sites: list[int] = Field(default_factory=list)
    time_budget: Optional[int] = None

    # Intermediate results
    secondary_structure: Optional[SecondaryStructure] = None
    candidates: list[CandidateSequence] = Field(default_factory=list)
    predictions: list[PredictionResult] = Field(default_factory=list)
    analogs: list[TargetMolecule] = Field(default_factory=list)
    specificity_results: list[SpecificityResult] = Field(default_factory=list)
    docking_plan: Optional[DockingPlan] = None
    docking_results: list[DockingResult] = Field(default_factory=list)
    spatial_ranks: list[SpatialRankResult] = Field(default_factory=list)
    recommendations: list[FinalRecommendation] = Field(default_factory=list)

    # Artifacts & logs
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    logs: list[dict[str, Any]] = Field(default_factory=list)

    # Pause/resume bookkeeping
    pending_input: Optional[dict[str, Any]] = None
    error_info: Optional[dict[str, Any]] = None
    context: WorkflowContext = Field(default_factory=WorkflowContext)

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat()
