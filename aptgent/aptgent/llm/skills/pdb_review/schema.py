from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class PdbReviewInput(BaseModel):
    summary: str


class PdbReviewOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    semantic_status: Literal["aptamer_like", "uncertain", "not_aptamer"] | str
    confidence: Literal["high", "medium", "low"] | str
    note: str = ""
