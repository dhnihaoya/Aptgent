from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


class DockingParamsParseInput(BaseModel):
    text: str
    current_params: dict | None = None
    candidate_count: int | None = None


class DockingParamsParseOutput(BaseModel):
    """Partial docking parameter overrides extracted from natural language.

    All numeric fields are optional. The downstream validator
    (``validate_docking_param_overrides``) clamps every field against the
    allowed range and is responsible for the final value used in
    ``state.docking_plan``.
    """

    model_config = ConfigDict(extra="ignore")

    top_k: Optional[int] = None
    exhaustiveness: Optional[int] = None
    num_modes: Optional[int] = None
    energy_range: Optional[float] = None
    grid_padding_angstrom: Optional[float] = None
    per_ligand_timeout_seconds: Optional[int] = None
    time_budget_hours: Optional[int] = None
    seed: Optional[int] = None
    action: Optional[Literal["apply", "skip", "use_llm_hint", "use_defaults"]] = None
