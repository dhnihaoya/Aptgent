from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aptgent.domain.models import SecondaryStructure
from aptgent.llm.skills.base import BaseSkill
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

    def propose_from_context(self, context: dict[str, Any]) -> dict[str, Any]:
        return self.invoke(context).raw

    def propose_events_from_context(self, context: dict[str, Any]):
        return self.invoke_json_events(context)

    def propose(
        self, sequence: str, structure: SecondaryStructure
    ) -> dict[str, Any]:
        return self.propose_from_context(
            self._context_from_sequence(sequence, structure)
        )


SiteProposalSkill._bind_directory(_SKILL_DIR)
