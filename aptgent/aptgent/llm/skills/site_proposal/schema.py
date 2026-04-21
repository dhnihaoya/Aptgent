from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SiteProposalInput(BaseModel):
    sequence: str
    secondary_structure: dict[str, Any] | None = None
    user_notes: str | None = None


class SiteProposalOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    proposed_sites: list[int] = Field(default_factory=list)
    reasoning: str = ""
    confidence: str = "unknown"


class SiteRephraseOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    proposed_sites: list[int] = Field(default_factory=list)
    reasoning: str = ""
