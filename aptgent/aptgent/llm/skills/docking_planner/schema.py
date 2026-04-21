from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class DockingPlannerInput(BaseModel):
    candidate_count: int
    machine_profile: dict[str, Any]
    time_budget_hours: int | None = None
    computed_top_k: int | None = None
    computed_time_budget_hours: int | None = None
    computed_grid_size: list[float] | None = None


class DockingPlannerOutput(BaseModel):
    """Only the free-text fields the LLM is allowed to contribute."""

    model_config = ConfigDict(extra="ignore")

    receptor_path_note: str = ""
    grid_center_note: str = ""
    reason: str = ""
