from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class IntakeInput(BaseModel):
    user_text: str


class IntakeOutput(BaseModel):
    """Raw (un-normalised) intake extraction.

    Validation is lenient: downstream ``validate_intake_result`` performs the
    real normalisation (sequence uppercasing, PDB ID validation, analog list
    cleanup). The schema here is just "did the LLM return the right keys?".
    """

    model_config = ConfigDict(extra="ignore")

    initial_sequence: str | None = None
    pdb_id: str | None = None
    input_mode: str | None = "direct"
    target_molecule: str | None = None
    modification_region: str | None = None
    analogs: list[str] = Field(default_factory=list)
    proposed_sites: list[int] = Field(default_factory=list)
    time_budget_hours: int | float | str | None = None
    mutation_ratio: float | None = None
    mixed_input_detected: bool = False
    missing_fields: list[str] = Field(default_factory=list)
    follow_up_question: str | None = None
