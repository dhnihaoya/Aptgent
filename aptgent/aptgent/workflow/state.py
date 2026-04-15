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

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat()
