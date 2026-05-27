from __future__ import annotations

from pathlib import Path
from typing import Any

from aptgent.llm.skills.base import BaseSkill
from aptgent.llm.skills.intake.schema import IntakeOutput

_SKILL_DIR = Path(__file__).resolve().parent


class IntakeSkill(BaseSkill):
    """Skill: extract structured intake fields from free-form user input."""

    output_schema = IntakeOutput

    def build_user_message(self, payload: Any) -> str:
        if isinstance(payload, str):
            return payload
        return super().build_user_message(payload)

    def extract(self, user_text: str) -> dict[str, Any]:
        return self.invoke(user_text).raw


IntakeSkill._bind_directory(_SKILL_DIR)
