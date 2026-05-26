from __future__ import annotations

from typing import Any

from aptgent.domain.text_utils import clean_text

from .coercion import coerce_int, coerce_int_list


def validate_site_proposal_result(result: Any, sequence_length: int) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise RuntimeError("Invalid site proposal response.")
    max_value = max(sequence_length - 1, 0)
    fallback_reasoning = (
        clean_text(result.get("reasoning"))
        or "Suggested from the current secondary-structure context."
    )
    fallback_confidence = (clean_text(result.get("confidence")) or "unknown").lower()
    region_assessment: list[dict[str, Any]] = []
    raw_regions = result.get("region_assessment")
    if isinstance(raw_regions, list):
        for index, raw in enumerate(raw_regions, start=1):
            if not isinstance(raw, dict):
                continue
            start = coerce_int(raw.get("start"))
            end = coerce_int(raw.get("end"))
            if start is not None and (start < 0 or start > max_value):
                start = None
            if end is not None and (end < 0 or end > max_value):
                end = None
            positions = coerce_int_list(
                raw.get("positions"),
                min_value=0,
                max_value=max_value,
            )
            rationale = clean_text(raw.get("rationale")) or clean_text(
                raw.get("reasoning")
            )
            region_assessment.append(
                {
                    "label": clean_text(raw.get("label")) or f"Region {index}",
                    "category": clean_text(raw.get("category")) or "unknown",
                    "start": start,
                    "end": end,
                    "positions": positions,
                    "rationale": rationale or "No rationale provided.",
                    "confidence": (
                        clean_text(raw.get("confidence")) or "unknown"
                    ).lower(),
                }
            )
    proposals: list[dict[str, Any]] = []
    raw_proposals = result.get("proposals")
    if isinstance(raw_proposals, list):
        for index, raw in enumerate(raw_proposals[:3], start=1):
            if not isinstance(raw, dict):
                continue
            sites = coerce_int_list(
                raw.get("proposed_sites"),
                min_value=0,
                max_value=max_value,
            )
            reasoning = clean_text(raw.get("reasoning")) or fallback_reasoning
            proposals.append(
                {
                    "label": clean_text(raw.get("label")) or f"Plan {index}",
                    "proposed_sites": sites,
                    "reasoning": reasoning,
                    "confidence": (
                        clean_text(raw.get("confidence")) or fallback_confidence
                    ).lower(),
                }
            )

    legacy_sites = coerce_int_list(
        result.get("proposed_sites"),
        min_value=0,
        max_value=max_value,
    )
    if not proposals:
        proposals = [
            {
                "label": "Recommended plan",
                "proposed_sites": legacy_sites,
                "reasoning": fallback_reasoning,
                "confidence": fallback_confidence,
            }
        ]
    first = proposals[0]
    return {
        "region_assessment": region_assessment,
        "proposals": proposals,
        "proposed_sites": list(first["proposed_sites"]),
        "reasoning": clean_text(first.get("reasoning")) or fallback_reasoning,
        "confidence": (
            clean_text(first.get("confidence")) or fallback_confidence
        ).lower(),
    }
