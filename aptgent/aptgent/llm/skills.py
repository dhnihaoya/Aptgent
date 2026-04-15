from __future__ import annotations

import json
from typing import Any

from aptgent.domain.models import SecondaryStructure, TargetMolecule
from aptgent.llm.client import LLMClient


SYSTEM_INTAKE = """You are an intake assistant for an aptamer design tool.
Extract the following fields from the user's natural language input:
- initial_sequence: the aptamer sequence (DNA or RNA). If missing, set to null.
- target_molecule: the small molecule name or SMILES the aptamer should bind to. If the user gives a non-English name (e.g., Chinese), translate it to the standard English common name. If missing, set to null.
- modification_region: optional description of regions the user wants to mutate (e.g., "loop region", "positions 10-20"). If missing, set to null.
- analogs: list of other small molecules to consider for specificity screening. If missing, empty list.
- time_budget_hours: optional time budget in hours. If missing, null.
- missing_fields: list of required fields that are still missing ("initial_sequence" and/or "target_molecule").
- follow_up_question: a concise question to ask the user to fill in the missing required fields. If nothing is missing, set to null.

Return ONLY a valid JSON object with these exact keys."""

DISPLAY_INTAKE = """You are an intake assistant for an aptamer design workflow.
Summarize the user's request in plain language for a chat UI.

Rules:
- Do not use JSON, markdown code fences, or key-value formatting.
- Mention the detected sequence and target molecule if present.
- If required fields are missing, say what is missing and ask one concise follow-up question.
- Keep it to 2-4 short sentences.
"""

SYSTEM_SITE_PROPOSAL = """You are a mutation advisor for aptamer design.
You are given a structured context payload for the current aptamer design run. The payload may include the aptamer sequence, predicted secondary structure, target-molecule metadata, user-request notes, workflow state, and extra context from future integrations.

Use whatever context is present. Do not assume every field exists.

Your task is to propose a list of mutation sites (0-based indices) that are likely to tolerate changes without destroying the overall fold.

Rules:
- Prefer loop regions and unpaired nucleotides over stems.
- Avoid the first and last 3 nucleotides unless explicitly requested.
- If the user has already constrained a region, treat that as a preference rather than a hard rule unless the context says otherwise.
- Return a JSON object with:
  - proposed_sites: list of integers (0-based indices)
  - reasoning: short explanation (1-2 sentences)
  - confidence: "high", "medium", or "low"

Return ONLY the JSON object."""

DISPLAY_SITE_PROPOSAL = """You are a mutation advisor for aptamer design.
You are given a structured context payload for the current aptamer design run. Explain, in a chat-friendly way, which positions or regions look safer to mutate.

Rules:
- Respond as concise Markdown bullets suitable for streaming in a chat UI.
- Mention candidate positions or regions and why they look mutation-tolerant.
- Mention uncertainty naturally when needed.
- Keep it brief and concrete.
"""

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

DISPLAY_ANALOG_SUGGESTION = """You are a chemoinformatics assistant.
Suggest a few specificity-control analogs in plain language for a chat UI.

Rules:
- Do not use JSON or markdown code fences.
- Mention each analog by name and a short reason.
- Keep it concise and readable.
"""

SYSTEM_DOCKING_PLANNER = """You are a computational chemistry advisor. A user wants to run molecular docking on a set of aptamer candidates.

Given:
- candidate_count: total number of candidates
- machine_profile: {cpu_count, memory_gb}
- time_budget_hours: user-provided time budget (may be null)

Recommend a practical docking draft using only parameters that can reasonably be inferred from this context.

You may recommend:
- recommended_time_budget_hours
- recommended_top_k
- recommended_grid_size: [x, y, z] in Angstroms

You must NOT invent:
- receptor_path
- grid_center

For receptor_path and grid_center, provide short notes telling the user what still needs manual confirmation.

Return ONLY a JSON object:
- recommended_time_budget_hours: integer or null
- recommended_top_k: integer
- recommended_grid_size: list of 3 numbers
- receptor_path_note: short string
- grid_center_note: short string
- reason: short explanation
"""

DISPLAY_DOCKING_PLANNER = """You are a computational chemistry advisor.
Recommend a practical docking draft for a chat UI.

Rules:
- Respond in Markdown bullet-list format.
- Do not use JSON or markdown code fences.
- Include every parameter below as a list item:
  - time budget
  - top-k
  - grid box size
  - receptor path status
  - grid center status
  - brief rationale
"""

SYSTEM_REPORT = """You are a scientific report assistant. You are given a ranked list of aptamer candidate predictions. Your job is to write a brief, factual explanation for why the top candidates are recommended.

You MUST NOT change the order, scores, or labels. Only summarize what the data shows.

Return a JSON object:
- summary: one-paragraph overall summary
- candidate_notes: dict mapping candidate_id -> one-sentence note

Return ONLY the JSON object."""

DISPLAY_REPORT = """You are a scientific report assistant.
Write a short, factual summary for a chat UI based on the ranked recommendations.

Rules:
- Do not use JSON or markdown code fences.
- Do not change rankings, scores, or labels.
- Keep it to one short paragraph.
"""


class IntakeSkill:
    def __init__(self, client: LLMClient | None = None) -> None:
        self.client = client or LLMClient()

    def extract(self, user_text: str) -> dict[str, Any]:
        return self.client.chat_json(SYSTEM_INTAKE, user_text)

    def extract_stream(self, user_text: str):
        return self.client.chat_stream(SYSTEM_INTAKE, user_text)

    def explain_extract_stream(self, user_text: str):
        return self.client.chat_text_stream(DISPLAY_INTAKE, user_text)


class SiteProposalSkill:
    def __init__(self, client: LLMClient | None = None) -> None:
        self.client = client or LLMClient()

    @staticmethod
    def _site_context_to_user_prompt(context: dict[str, Any]) -> str:
        return "Site proposal context:\n" + json.dumps(
            context,
            indent=2,
            ensure_ascii=False,
        )

    def propose_from_context(self, context: dict[str, Any]) -> dict[str, Any]:
        return self.client.chat_json(
            SYSTEM_SITE_PROPOSAL,
            self._site_context_to_user_prompt(context),
        )

    def propose_stream_from_context(self, context: dict[str, Any]):
        return self.client.chat_stream(
            SYSTEM_SITE_PROPOSAL,
            self._site_context_to_user_prompt(context),
        )

    def explain_propose_stream_from_context(self, context: dict[str, Any]):
        return self.client.chat_text_stream(
            DISPLAY_SITE_PROPOSAL,
            self._site_context_to_user_prompt(context),
        )

    def propose(
        self,
        sequence: str,
        structure: SecondaryStructure,
    ) -> dict[str, Any]:
        context = {
            "sequence": sequence,
            "secondary_structure": {
                "sequence": structure.sequence,
                "dot_bracket": structure.dot_bracket,
                "mfe_kcal_per_mol": structure.mfe,
                "features": dict(structure.features),
            },
        }
        return self.propose_from_context(context)

    def propose_stream(
        self,
        sequence: str,
        structure: SecondaryStructure,
    ):
        context = {
            "sequence": sequence,
            "secondary_structure": {
                "sequence": structure.sequence,
                "dot_bracket": structure.dot_bracket,
                "mfe_kcal_per_mol": structure.mfe,
                "features": dict(structure.features),
            },
        }
        return self.propose_stream_from_context(context)

    def explain_propose_stream(
        self,
        sequence: str,
        structure: SecondaryStructure,
    ):
        context = {
            "sequence": sequence,
            "secondary_structure": {
                "sequence": structure.sequence,
                "dot_bracket": structure.dot_bracket,
                "mfe_kcal_per_mol": structure.mfe,
                "features": dict(structure.features),
            },
        }
        return self.explain_propose_stream_from_context(context)

    def rephrase(self, sequence: str, user_text: str) -> dict[str, Any]:
        user = f"Sequence length: {len(sequence)}\nUser request: {user_text}"
        return self.client.chat_json(SYSTEM_SITE_REPHRASE, user)

    def rephrase_stream(self, sequence: str, user_text: str):
        user = f"Sequence length: {len(sequence)}\nUser request: {user_text}"
        return self.client.chat_stream(SYSTEM_SITE_REPHRASE, user)


class AnalogSuggestionSkill:
    def __init__(self, client: LLMClient | None = None) -> None:
        self.client = client or LLMClient()

    def suggest(self, target: TargetMolecule) -> dict[str, Any]:
        user = f"Target name: {target.resolved_name or target.input_text}\nSMILES: {target.smiles or 'unknown'}"
        return self.client.chat_json(SYSTEM_ANALOG_SUGGESTION, user)

    def suggest_stream(self, target: TargetMolecule):
        user = f"Target name: {target.resolved_name or target.input_text}\nSMILES: {target.smiles or 'unknown'}"
        return self.client.chat_stream(SYSTEM_ANALOG_SUGGESTION, user)

    def explain_suggest_stream(self, target: TargetMolecule):
        user = f"Target name: {target.resolved_name or target.input_text}\nSMILES: {target.smiles or 'unknown'}"
        return self.client.chat_text_stream(DISPLAY_ANALOG_SUGGESTION, user)


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

    def plan_stream(
        self,
        candidate_count: int,
        machine_profile: dict[str, Any],
        time_budget_hours: int | None,
    ):
        user = (
            f"Candidates: {candidate_count}\n"
            f"Machine: {json.dumps(machine_profile, ensure_ascii=False)}\n"
            f"Time budget (hours): {time_budget_hours if time_budget_hours is not None else 'not set'}"
        )
        return self.client.chat_stream(SYSTEM_DOCKING_PLANNER, user)

    def explain_plan_stream(
        self,
        candidate_count: int,
        machine_profile: dict[str, Any],
        time_budget_hours: int | None,
    ):
        user = (
            f"Candidates: {candidate_count}\n"
            f"Machine: {json.dumps(machine_profile, ensure_ascii=False)}\n"
            f"Time budget (hours): {time_budget_hours if time_budget_hours is not None else 'not set'}"
        )
        return self.client.chat_text_stream(DISPLAY_DOCKING_PLANNER, user)


class ReportSkill:
    def __init__(self, client: LLMClient | None = None) -> None:
        self.client = client or LLMClient()

    def summarize(self, recommendations: list[dict[str, Any]]) -> dict[str, Any]:
        user = "Recommendations (already sorted by final_priority):\n" + json.dumps(
            recommendations, indent=2, ensure_ascii=False
        )
        return self.client.chat_json(SYSTEM_REPORT, user)

    def summarize_stream(self, recommendations: list[dict[str, Any]]):
        user = "Recommendations (already sorted by final_priority):\n" + json.dumps(
            recommendations, indent=2, ensure_ascii=False
        )
        return self.client.chat_stream(SYSTEM_REPORT, user)

    def explain_summarize_stream(self, recommendations: list[dict[str, Any]]):
        user = "Recommendations (already sorted by final_priority):\n" + json.dumps(
            recommendations, indent=2, ensure_ascii=False
        )
        return self.client.chat_text_stream(DISPLAY_REPORT, user)
