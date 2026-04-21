from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ReportInput(BaseModel):
    recommendations: list[dict[str, Any]]


class ReportOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    summary: str = ""
    candidate_notes: dict[str, str] = Field(default_factory=dict)
