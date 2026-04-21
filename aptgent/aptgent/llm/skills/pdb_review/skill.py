from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aptgent.llm.skills.base import BaseSkill
from aptgent.llm.skills.pdb_review.schema import PdbReviewOutput

_SKILL_DIR = Path(__file__).resolve().parent


class PdbReviewSkill(BaseSkill):
    """Skill: semantic review of a PDB structure for aptamer relevance."""

    output_schema = PdbReviewOutput

    def build_user_message(self, payload: Any) -> str:
        if isinstance(payload, str):
            return payload
        if isinstance(payload, dict):
            return json.dumps(payload, indent=2, ensure_ascii=False)
        return super().build_user_message(payload)

    def review(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Rich review accepting structured payload with title, hetnam, chains, etc."""
        result = self.invoke(payload)
        return result.raw

    def review_summary(self, summary: str) -> dict[str, Any]:
        """Backward-compatible wrapper — accepts a plain-text summary string."""
        return self.review({"summary": summary})


PdbReviewSkill._bind_directory(_SKILL_DIR)
