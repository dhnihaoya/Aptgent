"""Heuristics for detecting whether free-form text looks like a full intake brief.

Extracted from :mod:`aptgent.tui.steps.intake` to keep the handler focused on
workflow orchestration.
"""
from __future__ import annotations

import re

EXPLICIT_SEQUENCE_FIELD = re.compile(r"\b(sequence|seq)\b\s*[:=]?\s*[ACGTU]", re.IGNORECASE)
INLINE_SEQUENCE_TOKEN = re.compile(r"\b[ACGTU]{4,}\b", re.IGNORECASE)

_TARGET_SIGNAL_TOKENS = ("target", "smiles", "ligand", "molecule")
_BRIEF_SIGNAL_TOKENS = (
    "design an aptamer",
    "aptamer for",
    "screening",
    "preference",
    "analog",
    "budget",
    "modification",
)
_EXPLICIT_FIELD_TOKENS = (
    "target",
    "smiles",
    "analog",
    "budget",
    "preference",
    "modification",
)


def looks_like_full_intake(text: str) -> bool:
    """Return True when ``text`` looks like a multi-field intake brief.

    The rule set errs on the side of treating long, structured text as a
    brief so the pipeline re-runs the LLM extractor rather than making the
    user paste individual fields again.
    """
    lowered = text.lower()
    has_multiline_brief = len([line for line in text.splitlines() if line.strip()]) > 1
    has_explicit_sequence_field = bool(EXPLICIT_SEQUENCE_FIELD.search(text))
    has_inline_sequence = bool(INLINE_SEQUENCE_TOKEN.search(text))
    has_target_signal = any(token in lowered for token in _TARGET_SIGNAL_TOKENS)
    has_brief_signal = any(token in lowered for token in _BRIEF_SIGNAL_TOKENS)

    explicit_field_count = int(has_explicit_sequence_field) + sum(
        1 for token in _EXPLICIT_FIELD_TOKENS if token in lowered
    )

    if has_multiline_brief and (has_explicit_sequence_field or has_target_signal or has_brief_signal):
        return True
    if has_explicit_sequence_field:
        return True
    if has_inline_sequence and (has_target_signal or has_brief_signal):
        return True
    if explicit_field_count >= 2:
        return True
    return any(phrase in lowered for phrase in ("design an aptamer", "aptamer for"))
