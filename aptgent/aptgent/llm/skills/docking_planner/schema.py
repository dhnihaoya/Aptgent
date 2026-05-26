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
    """LLM docking recommendations: top-k + exhaustiveness + notes only.

    The grid (box center/size) is derived deterministically from the aptamer
    geometry per Aptamers-2026.5.4.docx §2.4.4 ("docking search space ...
    cover the entire aptamer"), so the LLM no longer suggests grid_size.
    """

    model_config = ConfigDict(extra="ignore")

    recommended_exhaustiveness: int | None = None
    recommended_top_k: int | None = None
    receptor_path_note: str = ""
    grid_center_note: str = ""
    reason: str = ""
