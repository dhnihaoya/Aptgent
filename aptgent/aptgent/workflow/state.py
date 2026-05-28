from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aptgent.domain.enums import Status, Step
from aptgent.domain.models import (
    CandidateSequence,
    DockingPlan,
    DockingResult,
    FinalRecommendation,
    PdbChainCandidate,
    PdbLigandCandidate,
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
    proposed_sites: list[int] = Field(default_factory=list)
    time_budget_hours: Optional[int] = None
    phase: str = "initial"
    retry_count: int = 0
    last_resolution_error: Optional[str] = None
    resolved_once: bool = False


class SecondaryStructureContext(BaseModel):
    lookup_status: str = "idle"
    source: str = "rnafold"
    query_sequence: Optional[str] = None
    match_ids: list[str] = Field(default_factory=list)
    downloaded_artifact_path: Optional[str] = None
    note: Optional[str] = None


class PdbIntakeContext(BaseModel):
    pdb_id: Optional[str] = None
    input_mode: str = "direct"
    mixed_input_detected: bool = False
    download_status: str = "idle"
    analysis_status: str = "idle"
    artifact_path: Optional[str] = None
    title: Optional[str] = None
    chains: list[PdbChainCandidate] = Field(default_factory=list)
    ligands: list[PdbLigandCandidate] = Field(default_factory=list)
    recommended_chain_id: Optional[str] = None
    recommended_ligand_key: Optional[str] = None
    selected_chain_id: Optional[str] = None
    selected_ligand_key: Optional[str] = None
    user_sequence: Optional[str] = None
    derived_sequence: Optional[str] = None
    sequence_match_status: str = "unknown"
    semantic_validation_status: str = "unknown"
    semantic_note: Optional[str] = None
    review_category: Optional[str] = None
    review_target_match: Optional[str] = None
    review_confidence: Optional[str] = None
    needs_user_selection: bool = False
    error: Optional[str] = None


class TertiaryStructureContext(BaseModel):
    provider: Optional[str] = None
    receptor_source: Optional[str] = None
    receptor_status: str = "idle"
    job_id: Optional[str] = None
    result_path: Optional[str] = None
    error: Optional[str] = None


class SiteProposalContext(BaseModel):
    proposals: list[dict[str, Any]] = Field(default_factory=list)
    proposed_sites: list[int] = Field(default_factory=list)
    reasoning: Optional[str] = None
    confidence: Optional[str] = None
    confirmed_sites: list[int] = Field(default_factory=list)
    llm_context: dict[str, Any] = Field(default_factory=dict)
    extra_context: dict[str, Any] = Field(default_factory=dict)
    selection_source: str = ""
    selected_proposal_index: Optional[int] = None
    needs_regeneration: bool = False
    regeneration_reason: Optional[str] = None
    preserve_proposal_indexes: list[int] = Field(default_factory=list)


class DockingRecommendationContext(BaseModel):
    candidate_count: int = 0
    machine_profile: dict[str, Any] = Field(default_factory=dict)
    time_budget_hours: Optional[int] = None
    recommended_time_budget_hours: Optional[int] = None
    recommended_top_k: int = 0
    recommended_exhaustiveness: Optional[int] = None
    recommended_num_modes: Optional[int] = None
    recommended_energy_range: Optional[float] = None
    recommended_per_ligand_timeout_seconds: Optional[int] = None
    recommended_grid_padding_angstrom: Optional[float] = None
    recommended_seed: Optional[int] = None
    receptor_path_note: str = ""
    grid_center_note: str = ""
    reason: str = ""
    display_markdown: str = ""
    strategy: str = ""
    # phase progression: initial -> topk_selected -> awaiting_structures
    # -> structures_ready -> editing_form -> skipped
    phase: str = "initial"
    accepted: bool = False
    # Paths kept for UX (e.g. show user where exports went)
    sequences_export_dir: str = ""
    structures_dir: str = ""
    # Backward-compatible: still accept this field from old persisted runs.
    recommended_grid_size: list[float] = Field(default_factory=list)

    model_config = {"extra": "ignore"}


class SpecificityRecommendationContext(BaseModel):
    analog_names: list[str] = Field(default_factory=list)
    display_markdown: str = ""
    note: str = ""
    phase: str = "initial"
    accepted: bool = False


class WorkflowContext(BaseModel):
    intake: IntakeContext = Field(default_factory=IntakeContext)
    pdb_intake: PdbIntakeContext = Field(default_factory=PdbIntakeContext)
    secondary_structure: SecondaryStructureContext = Field(
        default_factory=SecondaryStructureContext
    )
    site_proposal: SiteProposalContext = Field(default_factory=SiteProposalContext)
    specificity_recommendation: SpecificityRecommendationContext = Field(
        default_factory=SpecificityRecommendationContext
    )
    docking_recommendation: DockingRecommendationContext = Field(
        default_factory=DockingRecommendationContext
    )
    tertiary_structure: TertiaryStructureContext = Field(
        default_factory=TertiaryStructureContext
    )


class RunState(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    schema_version: str = "1.0"
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
    final_report_markdown: str = ""
    final_report_context: dict[str, Any] = Field(default_factory=dict)

    # Pause/resume bookkeeping
    pending_input: Optional[dict[str, Any]] = None
    error_info: Optional[dict[str, Any]] = None
    context: WorkflowContext = Field(default_factory=WorkflowContext)

    # Per-step wall-clock timestamps (step.value -> ISO timestamp)
    step_timestamps: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _migrate_legacy_sites(self) -> RunState:
        """Sync legacy confirmed_mutation_sites into context on old-state load."""
        if self.confirmed_mutation_sites and not self.context.site_proposal.confirmed_sites:
            self.context.site_proposal.confirmed_sites = list(self.confirmed_mutation_sites)
        return self

    def set_mutation_sites(self, sites: list[int]) -> None:
        """Write mutation sites to both legacy field and context (single source migration helper)."""
        self.confirmed_mutation_sites = sites
        self.context.site_proposal.confirmed_sites = list(sites)

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat()
