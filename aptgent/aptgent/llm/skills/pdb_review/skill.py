from __future__ import annotations

from pathlib import Path
from typing import Any

from aptgent.llm.skills.base import BaseSkill
from aptgent.llm.skills.pdb_review.schema import PdbReviewOutput

_SKILL_DIR = Path(__file__).resolve().parent


class PdbReviewSkill(BaseSkill):
    """Skill: semantic sanity-check of a parsed PDB summary."""

    output_schema = PdbReviewOutput

    def build_user_message(self, payload: Any) -> str:
        if isinstance(payload, str):
            return payload
        return super().build_user_message(payload)

    def review_summary(self, summary: str) -> dict[str, Any]:
        return self.invoke(summary).raw


PdbReviewSkill._bind_directory(_SKILL_DIR)
