from __future__ import annotations

from pathlib import Path
from typing import Any

from aptgent.llm.skills.analog_parse.schema import AnalogParseOutput
from aptgent.llm.skills.base import BaseSkill

_SKILL_DIR = Path(__file__).resolve().parent


class AnalogParseSkill(BaseSkill):
    """Skill: extract molecule names from natural language."""

    output_schema = AnalogParseOutput

    def build_user_message(self, payload: Any) -> str:
        if isinstance(payload, str):
            return payload
        return super().build_user_message(payload)

    def parse_events(self, text: str):
        return self.invoke_json_events(text, enable_thinking=False)


AnalogParseSkill._bind_directory(_SKILL_DIR)
