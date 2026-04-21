from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aptgent.domain.models import SecondaryStructure
from aptgent.llm.skills.base import BaseSkill, load_prompt
from aptgent.llm.skills.site_proposal.schema import SiteProposalOutput

_SKILL_DIR = Path(__file__).resolve().parent


class SiteProposalSkill(BaseSkill):
    """Skill: suggest mutation-tolerant sites for an aptamer."""

    output_schema = SiteProposalOutput

    def build_user_message(self, payload: Any) -> str:
        if isinstance(payload, str):
            return payload
        if isinstance(payload, dict):
            return "Site proposal context:\n" + json.dumps(
                payload, indent=2, ensure_ascii=False
            )
        return super().build_user_message(payload)

    @staticmethod
    def _context_from_sequence(
        sequence: str, structure: SecondaryStructure
    ) -> dict[str, Any]:
        return {
            "sequence": sequence,
            "secondary_structure": {
                "sequence": structure.sequence,
                "dot_bracket": structure.dot_bracket,
                "mfe_kcal_per_mol": structure.mfe,
                "features": dict(structure.features),
            },
        }

    # -- legacy convenience wrappers (structured context) --
    def propose_from_context(self, context: dict[str, Any]) -> dict[str, Any]:
        return self.invoke(context).raw

    def propose_stream_from_context(self, context: dict[str, Any]):
        return self.invoke_stream(context)

    def explain_propose_stream_from_context(self, context: dict[str, Any]):
        return self.explain_stream(context)

    def propose(
        self, sequence: str, structure: SecondaryStructure
    ) -> dict[str, Any]:
        return self.propose_from_context(
            self._context_from_sequence(sequence, structure)
        )

    def propose_stream(self, sequence: str, structure: SecondaryStructure):
        return self.propose_stream_from_context(
            self._context_from_sequence(sequence, structure)
        )

    def explain_propose_stream(
        self, sequence: str, structure: SecondaryStructure
    ):
        return self.explain_propose_stream_from_context(
            self._context_from_sequence(sequence, structure)
        )

    # -- rephrase mode uses the secondary prompt file --
    _rephrase_prompt: str | None = None

    @classmethod
    def _rephrase_system_prompt(cls) -> str:
        if cls._rephrase_prompt is None:
            prompt = load_prompt(_SKILL_DIR, "system_rephrase.md")
            if prompt is None:
                raise FileNotFoundError(
                    "site_proposal skill: missing system_rephrase.md"
                )
            cls._rephrase_prompt = prompt
        return cls._rephrase_prompt

    def rephrase(self, sequence: str, user_text: str) -> dict[str, Any]:
        user = f"Sequence length: {len(sequence)}\nUser request: {user_text}"
        return self.client.chat_json(self._rephrase_system_prompt(), user)

    def rephrase_stream(self, sequence: str, user_text: str):
        user = f"Sequence length: {len(sequence)}\nUser request: {user_text}"
        return self.client.chat_stream(self._rephrase_system_prompt(), user)


SiteProposalSkill._bind_directory(_SKILL_DIR)
