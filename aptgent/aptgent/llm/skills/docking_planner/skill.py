from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aptgent.llm.skills.base import BaseSkill
from aptgent.llm.skills.docking_planner.schema import DockingPlannerOutput

_SKILL_DIR = Path(__file__).resolve().parent


class DockingPlannerSkill(BaseSkill):
    """Skill: annotate a deterministic docking draft with rationale / notes."""

    output_schema = DockingPlannerOutput

    @staticmethod
    def _build_user_message(
        candidate_count: int,
        machine_profile: dict[str, Any],
        time_budget_hours: int | None,
        computed_top_k: int | None = None,
        computed_time_budget_hours: int | None = None,
        target_smiles: str | None = None,
        target_name: str | None = None,
    ) -> str:
        payload = {
            "candidate_count": candidate_count,
            "machine_profile": machine_profile,
            "time_budget_hours": time_budget_hours,
            "computed_top_k": computed_top_k,
            "computed_time_budget_hours": computed_time_budget_hours,
        }
        if target_smiles:
            payload["target_smiles"] = target_smiles
        if target_name:
            payload["target_name"] = target_name
        return "Docking planner context:\n" + json.dumps(
            payload, indent=2, ensure_ascii=False
        )

    def build_user_message(self, payload: Any) -> str:
        if isinstance(payload, dict):
            return self._build_user_message(
                candidate_count=int(payload.get("candidate_count", 0)),
                machine_profile=dict(payload.get("machine_profile") or {}),
                time_budget_hours=payload.get("time_budget_hours"),
                computed_top_k=payload.get("computed_top_k"),
                computed_time_budget_hours=payload.get("computed_time_budget_hours"),
                target_smiles=payload.get("target_smiles"),
                target_name=payload.get("target_name"),
            )
        return super().build_user_message(payload)

    def plan(
        self,
        candidate_count: int,
        machine_profile: dict[str, Any],
        time_budget_hours: int | None,
        *,
        computed_top_k: int | None = None,
        computed_time_budget_hours: int | None = None,
        target_smiles: str | None = None,
        target_name: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "candidate_count": candidate_count,
            "machine_profile": machine_profile,
            "time_budget_hours": time_budget_hours,
            "computed_top_k": computed_top_k,
            "computed_time_budget_hours": computed_time_budget_hours,
        }
        if target_smiles is not None:
            payload["target_smiles"] = target_smiles
        if target_name is not None:
            payload["target_name"] = target_name
        return self.invoke(payload).raw

    def plan_stream(
        self,
        candidate_count: int,
        machine_profile: dict[str, Any],
        time_budget_hours: int | None,
        *,
        computed_top_k: int | None = None,
        computed_time_budget_hours: int | None = None,
        target_smiles: str | None = None,
        target_name: str | None = None,
    ):
        user = self._build_user_message(
            candidate_count,
            machine_profile,
            time_budget_hours,
            computed_top_k,
            computed_time_budget_hours,
            target_smiles,
            target_name,
        )
        return self.client.chat_stream(self.system_prompt, user)

    def explain_plan_stream(
        self,
        candidate_count: int,
        machine_profile: dict[str, Any],
        time_budget_hours: int | None,
        *,
        computed_top_k: int | None = None,
        computed_time_budget_hours: int | None = None,
        target_smiles: str | None = None,
        target_name: str | None = None,
    ):
        if self.display_prompt is None:
            raise RuntimeError(
                "docking_planner skill: display prompt is missing."
            )
        user = self._build_user_message(
            candidate_count,
            machine_profile,
            time_budget_hours,
            computed_top_k,
            computed_time_budget_hours,
            target_smiles,
            target_name,
        )
        return self.client.chat_text_stream(self.display_prompt, user)


DockingPlannerSkill._bind_directory(_SKILL_DIR)
