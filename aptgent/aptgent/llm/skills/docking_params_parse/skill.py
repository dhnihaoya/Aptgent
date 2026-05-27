from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aptgent.llm.skills.base import BaseSkill
from aptgent.llm.skills.docking_params_parse.schema import (
    DockingParamsParseOutput,
)

_SKILL_DIR = Path(__file__).resolve().parent


class DockingParamsParseSkill(BaseSkill):
    """Skill: extract docking-parameter intent from free-text user input."""

    output_schema = DockingParamsParseOutput

    @staticmethod
    def _build_user_message(
        text: str,
        current_params: dict[str, Any] | None,
        candidate_count: int | None,
    ) -> str:
        payload: dict[str, Any] = {"text": text}
        if current_params:
            payload["current_params"] = current_params
        if candidate_count is not None:
            payload["candidate_count"] = candidate_count
        return "Docking params parse context:\n" + json.dumps(
            payload, indent=2, ensure_ascii=False
        )

    def build_user_message(self, payload: Any) -> str:
        if isinstance(payload, str):
            return self._build_user_message(payload, None, None)
        if isinstance(payload, dict):
            return self._build_user_message(
                str(payload.get("text", "")),
                payload.get("current_params"),
                payload.get("candidate_count"),
            )
        return super().build_user_message(payload)

    def parse(
        self,
        text: str,
        *,
        current_params: dict[str, Any] | None = None,
        candidate_count: int | None = None,
    ) -> dict[str, Any]:
        payload = {
            "text": text,
            "current_params": current_params,
            "candidate_count": candidate_count,
        }
        return self.invoke(payload).raw

    def parse_events(
        self,
        text: str,
        *,
        current_params: dict[str, Any] | None = None,
        candidate_count: int | None = None,
    ):
        payload = {
            "text": text,
            "current_params": current_params,
            "candidate_count": candidate_count,
        }
        return self.invoke_json_events(payload, enable_thinking=False)


DockingParamsParseSkill._bind_directory(_SKILL_DIR)
