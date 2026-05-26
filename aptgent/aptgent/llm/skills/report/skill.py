from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aptgent.llm.skills.base import BaseSkill
from aptgent.llm.skills.report.schema import ReportOutput

_SKILL_DIR = Path(__file__).resolve().parent


class ReportSkill(BaseSkill):
    """Skill: write a Markdown report from deterministic workflow facts."""

    output_schema = ReportOutput

    def build_user_message(self, payload: Any) -> str:
        if isinstance(payload, dict) and "docking_candidates" in payload:
            return (
                "Final report context. The LLM may write prose, but must preserve "
                "all deterministic facts and must not invent rankings or scores.\n"
                + json.dumps(payload, indent=2, ensure_ascii=False)
            )
        if isinstance(payload, list):
            return "Recommendations (already sorted by final_priority):\n" + json.dumps(
                payload, indent=2, ensure_ascii=False
            )
        if isinstance(payload, dict) and "recommendations" in payload:
            return self.build_user_message(payload["recommendations"])
        return super().build_user_message(payload)

    def summarize(
        self, recommendations: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return self.invoke(recommendations).raw

    def summarize_stream(self, recommendations: list[dict[str, Any]]):
        return self.invoke_stream(recommendations)

    def explain_summarize_stream(self, recommendations: list[dict[str, Any]]):
        return self.explain_stream(recommendations)

    def write_markdown_stream(self, report_context: dict[str, Any]):
        return self.explain_stream(report_context)


ReportSkill._bind_directory(_SKILL_DIR)
