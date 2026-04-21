from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AnalogSuggestionInput(BaseModel):
    target_name: str
    smiles: str | None = None


class AnalogEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    smiles: str | None = None
    reason: str | None = None


class AnalogSuggestionOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    analogs: list[AnalogEntry] = Field(default_factory=list)
    note: str | None = None
