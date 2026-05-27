from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class DockingPlannerInput(BaseModel):
    candidate_count: int
    machine_profile: dict[str, Any]
    time_budget_hours: int | None = None
    computed_top_k: int | None = None
    computed_time_budget_hours: int | None = None


class DockingPlannerOutput(BaseModel):
    """LLM docking recommendations: numeric Vina knobs + notes.

    The grid (box center/size) is derived deterministically from the aptamer
    geometry to cover the entire structure, so the LLM no longer suggests
    grid_size. All numeric fields are clamped to safe ranges by
    ``validate_docking_recommendation_result`` before the workflow uses them.
    """

    model_config = ConfigDict(extra="ignore")

    recommended_exhaustiveness: int | None = None
    recommended_top_k: int | None = None
    recommended_num_modes: int | None = None
    recommended_energy_range: float | None = None
    recommended_grid_padding_angstrom: float | None = None
    recommended_per_ligand_timeout_seconds: int | None = None
    recommended_seed: int | None = None
    receptor_path_note: str = ""
    grid_center_note: str = ""
    reason: str = ""
