from __future__ import annotations

from pathlib import Path
from typing import Any

from aptgent.domain.models import TargetMolecule
from aptgent.llm.skills.analog_suggestion.schema import AnalogSuggestionOutput
from aptgent.llm.skills.base import BaseSkill

_SKILL_DIR = Path(__file__).resolve().parent


class AnalogSuggestionSkill(BaseSkill):
    """Skill: propose specificity-control analogs for a target molecule."""

    output_schema = AnalogSuggestionOutput

    @staticmethod
    def _message_for_target(target: TargetMolecule) -> str:
        return (
            f"Target name: {target.resolved_name or target.input_text}\n"
            f"SMILES: {target.smiles or 'unknown'}"
        )

    def build_user_message(self, payload: Any) -> str:
        if isinstance(payload, TargetMolecule):
            return self._message_for_target(payload)
        if isinstance(payload, str):
            return payload
        return super().build_user_message(payload)

    def suggest_events(self, target: TargetMolecule):
        return self.invoke_json_events(target, enable_thinking=False)

    # Legacy aliases.
    def suggest(self, target: TargetMolecule) -> dict[str, Any]:
        return self.invoke(target).raw

    def suggest_stream(self, target: TargetMolecule):
        return self.invoke_stream(target)

    def explain_suggest_stream(self, target: TargetMolecule):
        return self.explain_stream(target)


AnalogSuggestionSkill._bind_directory(_SKILL_DIR)
