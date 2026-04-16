from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from aptgent.domain.enums import Step


class TargetMolecule(BaseModel):
    input_text: str
    resolved_name: Optional[str] = None
    smiles: Optional[str] = None
    resolution_status: str = "pending"  # pending, resolved, failed, needs_confirmation


class Mutation(BaseModel):
    position: int  # 0-based index
    original: str
    mutated: str


class CandidateSequence(BaseModel):
    sequence: str
    mutations: list[Mutation] = Field(default_factory=list)
    edit_ratio: float = 0.0
    candidate_id: Optional[str] = None


class SecondaryStructure(BaseModel):
    sequence: str
    dot_bracket: str
    mfe: float
    features: dict[str, Any] = Field(default_factory=dict)


class PdbChainCandidate(BaseModel):
    chain_id: str
    sequence: str
    residue_count: int
    molecule_type: str = "nucleic_acid"
    note: str = ""


class PdbLigandCandidate(BaseModel):
    key: str
    identifier: str
    display_name: str
    chain_id: Optional[str] = None
    residue_number: Optional[int] = None
    atom_count: int = 0
    note: str = ""


class PdbAnalysisResult(BaseModel):
    pdb_id: str
    title: str = ""
    artifact_path: str = ""
    nucleic_acid_chains: list[PdbChainCandidate] = Field(default_factory=list)
    ligands: list[PdbLigandCandidate] = Field(default_factory=list)
    recommended_chain_id: Optional[str] = None
    recommended_ligand_key: Optional[str] = None
    needs_user_selection: bool = False
    semantic_status: str = "unknown"
    semantic_note: str = ""
    error: str = ""


class PredictionResult(BaseModel):
    candidate_id: str
    model_name: str
    target: str  # smiles or name
    score: float
    label: int
    probability: Optional[float] = None
    raw_outputs: dict[str, Any] = Field(default_factory=dict)


class DockingPlan(BaseModel):
    machine_profile: dict[str, Any] = Field(default_factory=dict)
    time_budget: Optional[int] = None
    recommended_top_k: int = 0
    reason: str = ""
    receptor_path: Optional[str] = None
    grid_center: Optional[list[float]] = None  # [x, y, z] in Angstroms
    grid_size: Optional[list[float]] = None    # [x, y, z] in Angstroms


class DockingResult(BaseModel):
    candidate_id: str
    docking_score: Optional[float] = None
    status: str = "pending"
    raw_outputs: dict[str, Any] = Field(default_factory=dict)


class SpecificityResult(BaseModel):
    candidate_id: str
    status: str = "pending"  # kept, removed
    failed_analogs: list[str] = Field(default_factory=list)
    raw_outputs: dict[str, Any] = Field(default_factory=dict)


class SpatialRankResult(BaseModel):
    candidate_id: str
    spatial_score: float
    detected_groups: list[str] = Field(default_factory=list)
    rank: int = 0
    raw_outputs: dict[str, Any] = Field(default_factory=dict)


class FinalRecommendation(BaseModel):
    candidate_id: str
    primary_score: float
    specificity_status: str = "pending"
    docking_score: Optional[float] = None
    spatial_rank: Optional[int] = None
    final_priority: int
    explanation: str = ""


class ArtifactRef(BaseModel):
    step: Step
    path: str
    mime_type: str = "application/json"
