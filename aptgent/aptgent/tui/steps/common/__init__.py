"""Shared TUI step utilities, split by domain.

All public symbols are re-exported here so that existing
``from aptgent.tui.steps.common import X`` imports continue to work.
"""

from __future__ import annotations

from aptgent.domain.enums import Step
from aptgent.domain.text_utils import clean_text
from aptgent.workflow.engine import TRANSITIONS

from .coercion import coerce_float, coerce_float_list, coerce_int, coerce_int_list
from .docking_plan import (
    DEFAULT_ENERGY_RANGE,
    DEFAULT_GRID_PADDING_ANGSTROM,
    DEFAULT_NUM_MODES,
    DEFAULT_PER_LIGAND_TIMEOUT_SECONDS,
    compute_deterministic_docking_plan,
    default_time_budget_hours,
    default_top_k,
    format_docking_recommendation_markdown,
    validate_docking_param_overrides,
    validate_docking_recommendation_result,
)
from .intake_format import (
    format_initial_intake_prompt,
    format_intake_confirmation,
    normalize_sequence,
    validate_intake_result,
)
from .llm_ui import run_llm_interaction
from .site_proposal_validate import validate_site_proposal_result
from .specificity_format import (
    format_specificity_recommendation_markdown,
    validate_analog_suggestion_result,
)

INITIAL_INTAKE_PLACEHOLDER = (
    "e.g. Design an aptamer for theophylline, sequence: GGGAAACCC... or provide a PDB ID"
)


def section_heading(title: str) -> str:
    return f"**{title}**"


def next_primary_step(step: Step) -> Step | None:
    """Return the first *different* step from this step's transition targets.

    For steps with multiple outgoing edges (e.g. DOCKING_SELECTION),
    this always picks the first target. Callers that need conditional
    branching should inspect TRANSITIONS directly.
    """
    targets = TRANSITIONS.get(step, [])
    if not targets:
        return None
    for candidate in targets:
        if candidate != step:
            return candidate
    return targets[0]


next_step = next_primary_step


__all__ = [
    "DEFAULT_ENERGY_RANGE",
    "DEFAULT_GRID_PADDING_ANGSTROM",
    "DEFAULT_NUM_MODES",
    "DEFAULT_PER_LIGAND_TIMEOUT_SECONDS",
    "INITIAL_INTAKE_PLACEHOLDER",
    "clean_text",
    "coerce_float",
    "coerce_float_list",
    "coerce_int",
    "coerce_int_list",
    "compute_deterministic_docking_plan",
    "default_time_budget_hours",
    "default_top_k",
    "format_docking_recommendation_markdown",
    "format_initial_intake_prompt",
    "format_intake_confirmation",
    "format_specificity_recommendation_markdown",
    "next_step",
    "next_primary_step",
    "normalize_sequence",
    "run_llm_interaction",
    "section_heading",
    "validate_analog_suggestion_result",
    "validate_docking_param_overrides",
    "validate_docking_recommendation_result",
    "validate_intake_result",
    "validate_site_proposal_result",
]
