from __future__ import annotations

import json
from typing import Any

from aptgent.domain.models import SecondaryStructure, TargetMolecule
from aptgent.llm.client import LLMClient


SYSTEM_INTAKE = """You are an intake assistant for an aptamer design tool.
Extract the following fields from the user's natural language input:
- initial_sequence: the aptamer sequence (DNA or RNA). If missing, set to null.
- target_molecule: the small molecule name or SMILES the aptamer should bind to. If missing, set to null.
- modification_region: optional description of regions the user wants to mutate (e.g., "loop region", "positions 10-20"). If missing, set to null.
- analogs: list of other small molecules to consider for specificity screening. If missing, empty list.
- time_budget_hours: optional time budget in hours. If missing, null.
- missing_fields: list of required fields that are still missing ("initial_sequence" and/or "target_molecule").
- follow_up_question: a concise question to ask the user to fill in the missing required fields. If nothing is missing, set to null.

Return ONLY a valid JSON object with these exact keys."""

SYSTEM_SITE_PROPOSAL = """You are a mutation advisor for aptamer design.
Given an aptamer sequence and its RNA secondary structure (dot-bracket notation + MFE), propose a list of mutation sites (0-based indices) that are likely to tolerate changes without destroying the overall fold.

Rules:
- Prefer loop regions and unpaired nucleotides over stems.
- Avoid the first and last 3 nucleotides unless explicitly requested.
- Return a JSON object with:
  - proposed_sites: list of integers (0-based indices)
  - reasoning: short explanation (1-2 sentences)
  - confidence: "high", "medium", or "low"

Return ONLY the JSON object."""

SYSTEM_SITE_REPHRASE = """You are a mutation advisor. The user described desired mutation sites in natural language. Convert this description into a concrete list of 0-based indices to mutate.

Return ONLY a JSON object:
- proposed_sites: list of integers
- reasoning: short explanation of how you interpreted the description"""

SYSTEM_ANALOG_SUGGESTION = """You are a chemoinformatics assistant. Given a target small molecule, suggest 2-4 structurally similar molecules that could be used as specificity controls in aptamer screening.

For each analog return:
- name: common name
- smiles: SMILES string if you know it, otherwise null
- reason: one-sentence rationale

Return ONLY a JSON object:
- analogs: list of {name, smiles, reason}
- note: optional brief note
"""

SYSTEM_DOCKING_PLANNER = """You are a computational chemistry advisor. A user wants to run molecular docking on a set of aptamer candidates.

Given:
- candidate_count: total number of candidates
- machine_profile: {cpu_count, memory_gb}
- time_budget_hours: user-provided time budget (may be null)

Recommend how many top candidates should enter docking. Consider CPU count and rough estimate that 1 candidate ~ 5-15 minutes depending on system size.

Return ONLY a JSON object:
- recommended_top_k: integer
- reason: one-sentence explanation
"""

SYSTEM_REPORT = """You are a scientific report assistant. You are given a ranked list of aptamer candidate predictions. Your job is to write a brief, factual explanation for why the top candidates are recommended.

You MUST NOT change the order, scores, or labels. Only summarize what the data shows.

Return a JSON object:
- summary: one-paragraph overall summary
- candidate_notes: dict mapping candidate_id -> one-sentence note

Return ONLY the JSON object."""


class IntakeSkill:
    def __init__(self, client: LLMClient | None = None) -> None:
        self.client = client or LLMClient()

    def extract(self, user_text: str) -> dict[str, Any]:
        return self.client.chat_json(SYSTEM_INTAKE, user_text)


class SiteProposalSkill:
    def __init__(self, client: LLMClient | None = None) -> None:
        self.client = client or LLMClient()

    def propose(
        self,
        sequence: str,
        structure: SecondaryStructure,
    ) -> dict[str, Any]:
        user = (
            f"Sequence: {sequence}\n"
            f"Dot-bracket: {structure.dot_bracket}\n"
            f"MFE: {structure.mfe} kcal/mol"
        )
        return self.client.chat_json(SYSTEM_SITE_PROPOSAL, user)

    def rephrase(self, sequence: str, user_text: str) -> dict[str, Any]:
        user = f"Sequence length: {len(sequence)}\nUser request: {user_text}"
        return self.client.chat_json(SYSTEM_SITE_REPHRASE, user)


class AnalogSuggestionSkill:
    def __init__(self, client: LLMClient | None = None) -> None:
        self.client = client or LLMClient()

    def suggest(self, target: TargetMolecule) -> dict[str, Any]:
        user = f"Target name: {target.resolved_name or target.input_text}\nSMILES: {target.smiles or 'unknown'}"
        return self.client.chat_json(SYSTEM_ANALOG_SUGGESTION, user)


class DockingPlannerSkill:
    def __init__(self, client: LLMClient | None = None) -> None:
        self.client = client or LLMClient()

    def plan(
        self,
        candidate_count: int,
        machine_profile: dict[str, Any],
        time_budget_hours: int | None,
    ) -> dict[str, Any]:
        user = (
            f"Candidates: {candidate_count}\n"
            f"Machine: {json.dumps(machine_profile, ensure_ascii=False)}\n"
            f"Time budget (hours): {time_budget_hours if time_budget_hours is not None else 'not set'}"
        )
        return self.client.chat_json(SYSTEM_DOCKING_PLANNER, user)


class ReportSkill:
    def __init__(self, client: LLMClient | None = None) -> None:
        self.client = client or LLMClient()

    def summarize(self, recommendations: list[dict[str, Any]]) -> dict[str, Any]:
        user = "Recommendations (already sorted by final_priority):\n" + json.dumps(
            recommendations, indent=2, ensure_ascii=False
        )
        return self.client.chat_json(SYSTEM_REPORT, user)
