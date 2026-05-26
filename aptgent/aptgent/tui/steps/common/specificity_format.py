from __future__ import annotations

from typing import Any

from aptgent.domain.text_utils import clean_text


def validate_analog_suggestion_result(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise RuntimeError("Invalid analog suggestion response.")
    analogs: list[dict[str, str | None]] = []
    raw_analogs = result.get("analogs", [])
    if isinstance(raw_analogs, list):
        for raw in raw_analogs:
            if not isinstance(raw, dict):
                continue
            name = clean_text(raw.get("name"))
            if not name:
                continue
            analogs.append(
                {
                    "name": name,
                    "smiles": clean_text(raw.get("smiles")),
                    "reason": clean_text(raw.get("reason")),
                }
            )
    return {
        "analogs": analogs,
        "note": clean_text(result.get("note")),
    }


def format_specificity_recommendation_markdown(
    *,
    target_name: str,
    analogs: list[dict[str, str | None]],
    note: str | None = None,
) -> str:
    from . import section_heading
    heading_target = target_name or "the current target"
    if not analogs:
        return (
            f"{section_heading('Recommended Specificity Analogs')}\n\n"
            f"No strong analog recommendations were returned for **{heading_target}**."
        )

    lines = [
        section_heading("Recommended Specificity Analogs"),
        "",
        f"Target: **{heading_target}**",
        "",
    ]
    for analog in analogs:
        name = analog.get("name") or "Unnamed analog"
        reason = analog.get("reason") or "Relevant structural neighbor for specificity screening."
        lines.append(f"- **{name}**: {reason}")
    if note:
        lines.extend(["", f"Note: {note}"])
    return "\n".join(lines)
