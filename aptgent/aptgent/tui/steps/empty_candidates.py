from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EmptyCandidateRecovery:
    needs_regeneration: bool
    reason: str
    guidance: str
    preserve_proposal_indexes: list[int]


def is_empty_enumeration_result(state: Any) -> bool:
    """Return True when empty candidates represent an exhausted mutation search."""
    if state.candidates:
        return False

    context = state.context.site_proposal
    feedback = dict(context.extra_context.get("site_selection_feedback") or {})
    if feedback.get("reason") == "no_positive_candidates":
        return True
    if context.regeneration_reason and (
        state.confirmed_mutation_sites or context.selection_source in {"llm", "custom"}
    ):
        return True
    return bool(
        state.confirmed_mutation_sites
        and context.selection_source in {"llm", "custom"}
    )


def prepare_empty_candidate_recovery(
    state: Any,
    *,
    total: int | None = None,
    hits: int = 0,
    kept: int = 0,
) -> EmptyCandidateRecovery:
    """Persist no-positive-candidate feedback for scoring/back recovery paths."""
    context = state.context.site_proposal
    feedback = dict(context.extra_context.get("site_selection_feedback") or {})
    selected_index = context.selected_proposal_index
    needs_regeneration = context.selection_source == "llm"

    preserve_indexes: list[int] = []
    if needs_regeneration and selected_index in (0, 1):
        preserve_indexes = [2]
    elif needs_regeneration and selected_index == 2:
        preserve_indexes = [0, 1]

    reason = (
        feedback.get("message")
        or context.regeneration_reason
        or _empty_result_reason(total=total, hits=hits, kept=kept)
    )
    guidance = feedback.get("guidance") or empty_result_guidance(
        selection_source=context.selection_source,
        selected_index=selected_index,
    )

    state.candidates = []
    state.predictions = []
    context.needs_regeneration = needs_regeneration
    context.regeneration_reason = reason if needs_regeneration else None
    context.preserve_proposal_indexes = preserve_indexes
    context.extra_context = {
        **dict(context.extra_context),
        "site_selection_feedback": {
            "reason": "no_positive_candidates",
            "message": reason,
            "guidance": guidance,
            "selected_sites": list(state.confirmed_mutation_sites),
            "selection_source": context.selection_source,
            "selected_proposal_index": selected_index,
            "preserve_proposal_indexes": preserve_indexes,
            "previous_proposals": list(context.proposals),
        },
    }

    return EmptyCandidateRecovery(
        needs_regeneration=needs_regeneration,
        reason=reason,
        guidance=guidance,
        preserve_proposal_indexes=preserve_indexes,
    )


def clear_site_selection_retry_feedback(state: Any) -> None:
    context = state.context.site_proposal
    context.needs_regeneration = False
    context.regeneration_reason = None
    context.preserve_proposal_indexes = []
    if "site_selection_feedback" in context.extra_context:
        extra_context = dict(context.extra_context)
        extra_context.pop("site_selection_feedback", None)
        context.extra_context = extra_context


def _empty_result_reason(
    *,
    total: int | None,
    hits: int,
    kept: int,
) -> str:
    if total is None:
        return "No binding candidates were found for the selected mutation sites."
    return (
        f"No binding candidates were found after enumerating {total:,} mutants "
        f"({hits:,} hits, {kept:,} kept)."
    )


def empty_result_guidance(
    *,
    selection_source: str,
    selected_index: int | None,
) -> str:
    if selection_source != "llm":
        return (
            "The custom mutation sites produced no predicted binding mutations. "
            "Do not regenerate LLM recommendations automatically; let the user choose "
            "another set of sites."
        )
    if selected_index in (0, 1):
        return (
            "The selected conservative/aggressive LLM plan produced no predicted "
            "binding mutations. Keep the alternate plan unchanged, and regenerate "
            "plans 1 and 2 with a larger mutation space than the failed sites."
        )
    if selected_index == 2:
        return (
            "The selected alternate LLM plan produced no predicted binding mutations. "
            "Keep plans 1 and 2 unchanged, and regenerate only the alternate plan "
            "with a different direction."
        )
    return (
        "The selected LLM plan produced no predicted binding mutations. Regenerate "
        "recommendations using the failed sites and previous proposals as feedback."
    )
