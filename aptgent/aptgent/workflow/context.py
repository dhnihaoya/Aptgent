from __future__ import annotations

from typing import Any

from aptgent.domain.models import TargetMolecule
from aptgent.workflow.state import RunState


def _clean_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = " ".join(value.split())
    return value or None


def get_sequence(state: RunState) -> str | None:
    return _clean_text(state.context.intake.sequence) or _clean_text(
        state.input_payload.get("initial_sequence")
    )


def get_target_label(state: RunState) -> str | None:
    if state.target_molecule is not None:
        resolved = state.target_molecule.resolved_name or state.target_molecule.input_text
        text = _clean_text(resolved)
        if text:
            return text
    return (
        _clean_text(state.context.intake.target_label)
        or _clean_text(state.context.intake.target_input)
        or _clean_text(state.input_payload.get("target_molecule"))
    )


def get_user_brief(state: RunState) -> str | None:
    return _clean_text(state.context.intake.user_brief) or _clean_text(
        state.input_payload.get("user_text")
    )


def record_intake_context(
    state: RunState,
    *,
    user_brief: str | None = None,
    sequence: str | None = None,
    target_text: str | None = None,
    resolved_target: TargetMolecule | None = None,
    modification_region: str | None = None,
    analogs: list[str] | None = None,
    time_budget_hours: int | None = None,
) -> None:
    context = state.context.intake
    if user_brief is not None:
        context.user_brief = _clean_text(user_brief)
    if sequence is not None:
        context.sequence = _clean_text(sequence)
    if target_text is not None:
        context.target_input = _clean_text(target_text)
    if resolved_target is not None:
        context.target_label = _clean_text(
            resolved_target.resolved_name or resolved_target.input_text
        )
    if modification_region is not None:
        context.modification_region = _clean_text(modification_region)
    if analogs is not None:
        context.analogs = [text for item in analogs if (text := _clean_text(item))]
    if time_budget_hours is not None:
        context.time_budget_hours = time_budget_hours


def record_site_proposal_context(
    state: RunState,
    *,
    proposed_sites: list[int] | None = None,
    reasoning: str | None = None,
    confidence: str | None = None,
    confirmed_sites: list[int] | None = None,
) -> None:
    context = state.context.site_proposal
    if proposed_sites is not None:
        context.proposed_sites = list(proposed_sites)
    if reasoning is not None:
        context.reasoning = _clean_text(reasoning)
    if confidence is not None:
        context.confidence = _clean_text(confidence)
    if confirmed_sites is not None:
        context.confirmed_sites = list(confirmed_sites)


def record_docking_recommendation_context(
    state: RunState,
    *,
    candidate_count: int,
    machine_profile: dict[str, Any],
    time_budget_hours: int | None,
    recommended_time_budget_hours: int | None,
    recommended_top_k: int,
    recommended_grid_size: list[float] | None,
    receptor_path_note: str,
    grid_center_note: str,
    reason: str,
    display_markdown: str = "",
    strategy: str = "",
    phase: str = "initial",
    accepted: bool = False,
) -> None:
    context = state.context.docking_recommendation
    context.candidate_count = candidate_count
    context.machine_profile = dict(machine_profile)
    context.time_budget_hours = time_budget_hours
    context.recommended_time_budget_hours = recommended_time_budget_hours
    context.recommended_top_k = recommended_top_k
    context.recommended_grid_size = list(recommended_grid_size or [])
    context.receptor_path_note = _clean_text(receptor_path_note) or ""
    context.grid_center_note = _clean_text(grid_center_note) or ""
    context.reason = reason
    context.display_markdown = display_markdown
    context.strategy = strategy
    context.phase = phase
    context.accepted = accepted


def build_run_overview(state: RunState) -> str:
    target = get_target_label(state)
    sequence = get_sequence(state)
    user_brief = get_user_brief(state)

    parts: list[str] = []
    if target:
        parts.append(target)
    if sequence:
        parts.append(sequence)
    elif user_brief:
        parts.append(user_brief)
    return " | ".join(parts) if parts else "Untitled run"
