from __future__ import annotations

from typing import Any

from aptgent.adapters.pdb_analysis import normalize_pdb_id
from aptgent.domain.models import TargetMolecule
from aptgent.domain.text_utils import clean_text

from .coercion import coerce_int


def normalize_sequence(value: Any) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    sequence = "".join(ch for ch in text.upper() if not ch.isspace())
    allowed = {"A", "C", "G", "T", "U"}
    if not sequence or any(ch not in allowed for ch in sequence):
        return None
    return sequence


def validate_intake_result(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise RuntimeError("Invalid intake response.")
    missing_fields = []
    for item in result.get("missing_fields", []):
        text = clean_text(item)
        if text:
            missing_fields.append(text)
    proposed_sites_raw = result.get("proposed_sites") or []
    proposed_sites = [
        s for s in proposed_sites_raw if isinstance(s, int) and s > 0
    ] if isinstance(proposed_sites_raw, list) else []

    return {
        "initial_sequence": normalize_sequence(result.get("initial_sequence")),
        "pdb_id": normalize_pdb_id(clean_text(result.get("pdb_id"))),
        "input_mode": clean_text(result.get("input_mode")) or "direct",
        "target_molecule": clean_text(result.get("target_molecule")),
        "modification_region": clean_text(result.get("modification_region")),
        "analogs": [
            text for text in (clean_text(item) for item in result.get("analogs", []))
            if text
        ] if isinstance(result.get("analogs"), list) else [],
        "time_budget_hours": coerce_int(result.get("time_budget_hours")),
        "mixed_input_detected": bool(result.get("mixed_input_detected")),
        "missing_fields": missing_fields,
        "follow_up_question": clean_text(result.get("follow_up_question")),
        "proposed_sites": proposed_sites,
    }


def format_initial_intake_prompt() -> str:
    from . import section_heading
    return "\n".join(
        [
            section_heading("Step 1: Intake"),
            "",
            "- Describe the aptamer design task in plain language.",
            "- You can provide a sequence and target molecule directly.",
            "- You can also provide a PDB ID and let the workflow extract the sequence and any bound ligand candidates.",
        ]
    )


def format_intake_confirmation(
    *,
    sequence: str,
    target_text: str,
    resolved: TargetMolecule,
    modification_region: str | None,
    analogs: list[str],
    time_budget_hours: int | None,
) -> str:
    from . import section_heading
    lines = [
        section_heading("Captured Intake Details"),
        "",
        f"- **Sequence**: `{sequence}`",
    ]
    if resolved.resolution_status == "resolved":
        lines.append(
            f"- **Target**: **{resolved.resolved_name or target_text}**"
            f" (`{resolved.smiles}`)"
        )
    else:
        lines.append(f"- **Target**: {target_text} (`resolution failed`)")
    if modification_region:
        lines.append(f"- **Requested modification region**: {modification_region}")
    if analogs:
        lines.append(
            "- **Specificity analogs**: "
            + ", ".join(f"`{analog}`" for analog in analogs)
        )
    if time_budget_hours is not None:
        lines.append(f"- **Time budget**: {time_budget_hours} hour(s)")
    return "\n".join(lines)
