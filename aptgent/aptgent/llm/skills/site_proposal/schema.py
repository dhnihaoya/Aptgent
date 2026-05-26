from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SiteProposalInput(BaseModel):
    sequence: str
    secondary_structure: dict[str, Any] | None = None
    user_notes: str | None = None


class SiteProposalPlan(BaseModel):
    model_config = ConfigDict(extra="ignore")

    label: str = ""
    proposed_sites: list[int] = Field(default_factory=list)
    reasoning: str = ""
    confidence: str = "unknown"


class SiteRegionAssessment(BaseModel):
    model_config = ConfigDict(extra="ignore")

    label: str = ""
    category: str = ""
    start: int | None = None
    end: int | None = None
    positions: list[int] = Field(default_factory=list)
    rationale: str = ""
    confidence: str = "unknown"


class SiteProposalOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    region_assessment: list[SiteRegionAssessment] = Field(default_factory=list)
    proposals: list[SiteProposalPlan] = Field(default_factory=list)
    proposed_sites: list[int] = Field(default_factory=list)
    reasoning: str = ""
    confidence: str = "unknown"
