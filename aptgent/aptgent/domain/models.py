from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class TargetMolecule(BaseModel):
    input_text: str
    resolved_name: Optional[str] = None
    smiles: Optional[str] = None
    resolution_status: str = "pending"  # pending, resolved, failed, needs_confirmation
    error_detail: Optional[str] = None  # "network" | "not_found" | None


class Mutation(BaseModel):
    position: int  # 0-based index
    original: str
    mutated: str

    @field_validator("position")
    @classmethod
    def _position_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("position must be non-negative")
        return v

    @field_validator("original", "mutated")
    @classmethod
    def _valid_base(cls, v: str) -> str:
        if len(v) != 1 or v.upper() not in {"A", "T", "G", "C", "U"}:
            raise ValueError(f"invalid nucleotide base: {v!r}")
        return v


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
    semantic_category: str = "uncertain"
    semantic_target_match: str = "unknown"
    semantic_confidence: str = "medium"
    error: str = ""


class PredictionResult(BaseModel):
    candidate_id: str
    model_name: str
    target: str  # smiles or name
    score: float
    label: int
    probability: Optional[float] = None
    raw_outputs: dict[str, Any] = Field(default_factory=dict)


class GridBox(BaseModel):
    """Per-receptor docking search box in Angstroms."""

    center: list[float]  # [x, y, z]
    size: list[float]    # [x, y, z]

    @field_validator("center", "size")
    @classmethod
    def _xyz_length(cls, v: list[float]) -> list[float]:
        if len(v) != 3:
            raise ValueError("must contain exactly 3 values [x, y, z]")
        return v

    @field_validator("size")
    @classmethod
    def _positive_size(cls, v: list[float]) -> list[float]:
        if any(s <= 0 for s in v):
            raise ValueError("size values must be positive")
        return v


class DockingPlan(BaseModel):
    """Per-candidate docking plan.

    Each candidate aptamer gets its own 3D structure (RNAComposer/manual)
    and Vina runs once per (receptor, ligand) pair with the search box
    covering the entire aptamer.
    """

    machine_profile: dict[str, Any] = Field(default_factory=dict)
    time_budget: Optional[int] = None
    recommended_top_k: int = 0
    affinity_top_k: int = 0
    reason: str = ""

    receptor_source: str = "manual"  # "manual" | "rnacomposer" | "rnacomposer-moe" | "moe-manual"
    receptor_paths: dict[str, str] = Field(default_factory=dict)
    receptor_pdb_paths: dict[str, str] = Field(default_factory=dict)
    grid_boxes: dict[str, GridBox] = Field(default_factory=dict)
    grid_padding_angstrom: float = 4.0

    exhaustiveness: int = 8
    num_modes: int = 9
    energy_range: float = 3.0
    seed: Optional[int] = None
    # None = use docking.per_ligand_timeout_seconds from workflow.toml.
    per_ligand_timeout_seconds: Optional[int] = None

    model_config = {"extra": "ignore"}

    @property
    def receptor_path(self) -> Optional[str]:
        """Legacy compatibility accessor: returns the first receptor path."""
        if self.receptor_paths:
            return next(iter(self.receptor_paths.values()))
        return None

    @property
    def grid_center(self) -> Optional[list[float]]:
        """Legacy compatibility accessor: returns the first box center."""
        if self.grid_boxes:
            return list(next(iter(self.grid_boxes.values())).center)
        return None

    @property
    def grid_size(self) -> Optional[list[float]]:
        """Legacy compatibility accessor: returns the first box size."""
        if self.grid_boxes:
            return list(next(iter(self.grid_boxes.values())).size)
        return None


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
