from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AnalogParseInput(BaseModel):
    text: str


class AnalogParseOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    molecule_names: list[str] = Field(default_factory=list)
