"""Display formatting helpers for candidate scoring and enumeration previews."""

from __future__ import annotations

from typing import Any

RANKED_PREVIEW_TOP_N = 10
ENUM_PREVIEW_TOP_N = 10


def format_ranked_candidates(preds: list[Any], top_n: int = RANKED_PREVIEW_TOP_N) -> str:
    lines = []
    for rank_idx, pred in enumerate(preds[:top_n], start=1):
        label_str = "Binding" if pred.label == 1 else "Non-binding"
        rs = pred.raw_outputs.get("rank_sum")
        rs_str = f"rank_sum={rs}" if rs is not None else ""
        prob_str = f"P={pred.probability:.4f}" if pred.probability is not None else ""
        parts = [rs_str, prob_str]
        detail = ", ".join(p for p in parts if p)
        lines.append(
            f"  #{rank_idx} {pred.candidate_id}: {detail} ({label_str})"
        )
    if len(preds) > top_n:
        lines.append(f"  ... and {len(preds) - top_n} more")
    return "\n".join(lines)


def format_enumeration_preview(
    candidates: list[Any],
    predictions: list[Any],
    top_n: int = ENUM_PREVIEW_TOP_N,
) -> str:
    lines = []
    for candidate, pred in zip(candidates[:top_n], predictions[:top_n]):
        label_str = "Bind" if pred.label == 1 else "Non-bind"
        mut_str = ", ".join(
            f"{m.position}:{m.original}>{m.mutated}"
            for m in candidate.mutations
        )
        lines.append(
            f"  {candidate.candidate_id}: {label_str} P={pred.probability:.4f} | {mut_str}"
        )
    if len(candidates) > top_n:
        lines.append(f"  ... and {len(candidates) - top_n} more")
    return "\n".join(lines)
