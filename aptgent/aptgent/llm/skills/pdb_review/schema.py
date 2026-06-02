from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class PdbReviewInput(BaseModel):
    summary: str


class PdbReviewOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    category: Literal[
        "aptamer_small_molecule",
        "aptamer_protein",
        "ribozyme_or_catalytic",
        "structural_rna",
        "other_nucleic_acid",
        "not_nucleic_acid",
        "uncertain",
    ] = "uncertain"
    target_match: Literal["matches", "mismatches", "unknown"] = "unknown"
    confidence: Literal["high", "medium", "low"] = "medium"
    note: str = ""

    @property
    def semantic_status(self) -> str:
        """Backward-compatible mapping to the old three-state label."""
        _APTAMER = {"aptamer_small_molecule", "aptamer_protein"}
        _NOT = {"not_nucleic_acid", "structural_rna", "other_nucleic_acid"}
        if self.category in _APTAMER:
            return "aptamer_like"
        if self.category in _NOT:
            return "not_aptamer"
        return "uncertain"
