from __future__ import annotations

from typing import Any, Callable

from aptgent.adapters.pdb_analysis import normalize_pdb_id
from aptgent.domain.models import TargetMolecule
from aptgent.workflow.engine import TRANSITIONS

INITIAL_INTAKE_PLACEHOLDER = (
    "e.g. Design an aptamer for theophylline, sequence: GGGAAACCC... or provide a PDB ID"
)


def section_heading(title: str) -> str:
    return f"**{title}**"


def next_step(step) -> Any:
    targets = TRANSITIONS.get(step, [])
    if not targets:
        return None
    for candidate in targets:
        if candidate != step:
            return candidate
    return targets[0]


def clean_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def normalize_sequence(value: Any) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    sequence = "".join(ch for ch in text.upper() if not ch.isspace())
    allowed = {"A", "C", "G", "T", "U"}
    if not sequence or any(ch not in allowed for ch in sequence):
        return None
    return sequence


def coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip():
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def coerce_int_list(
    values: Any,
    *,
    min_value: int | None = None,
    max_value: int | None = None,
) -> list[int]:
    if not isinstance(values, list):
        return []
    result: list[int] = []
    seen: set[int] = set()
    for item in values:
        value = coerce_int(item)
        if value is None:
            continue
        if min_value is not None and value < min_value:
            continue
        if max_value is not None and value > max_value:
            continue
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def coerce_float_list(values: Any, *, exact_len: int | None = None) -> list[float]:
    if not isinstance(values, list):
        return []
    result = [value for item in values if (value := coerce_float(item)) is not None]
    if exact_len is not None and len(result) != exact_len:
        return []
    return result


def run_llm_interaction(
    screen: Any,
    *,
    display_stream: Callable[[], Any] | None,
    structured_call: Callable[[], Any],
    structured_client: Any | None = None,
) -> dict[str, Any]:
    from textual.worker import get_current_worker

    worker = get_current_worker()
    if worker.is_cancelled:
        return {}

    bubble = None
    thinking_bubble = None
    display_error: Exception | None = None

    if display_stream is not None:
        def make_thinking_bubble() -> None:
            nonlocal thinking_bubble
            thinking_bubble = screen.add_thinking_message()

        screen.app.call_from_thread(screen.clear_activity)
        screen.app.call_from_thread(make_thinking_bubble)
        try:
            for chunk in display_stream():
                if worker.is_cancelled:
                    return {}
                if isinstance(chunk, dict):
                    chunk_type = chunk.get("type", "content")
                    text = chunk.get("text", "")
                else:
                    chunk_type = "content"
                    text = chunk
                if not text:
                    continue
                if chunk_type == "reasoning":
                    screen.app.call_from_thread(thinking_bubble.append_text, text)
                    continue
                if bubble is None:
                    def make_bubble() -> None:
                        nonlocal bubble
                        bubble = screen.add_streaming_message(markdown=True)

                    screen.app.call_from_thread(make_bubble)
                screen.app.call_from_thread(bubble.append_text, text)
        except Exception as exc:
            display_error = exc
        finally:
            if thinking_bubble:
                if thinking_bubble.has_content:
                    screen.app.call_from_thread(thinking_bubble.finalize)
                else:
                    screen.app.call_from_thread(thinking_bubble.remove)
            if bubble:
                screen.app.call_from_thread(bubble.finalize)

    if worker.is_cancelled:
        return {}

    screen.app.call_from_thread(screen.update_activity, "Processing structured result...")
    result = structured_call()
    if not isinstance(result, dict):
        raise RuntimeError("LLM returned a non-object response.")

    if display_error is not None:
        screen.app.call_from_thread(
            screen.add_system_message,
            f"LLM explanation unavailable; using structured fallback. {display_error}",
            "warning-text",
        )

    return result


def validate_intake_result(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise RuntimeError("Invalid intake response.")
    missing_fields = []
    for item in result.get("missing_fields", []):
        text = clean_text(item)
        if text:
            missing_fields.append(text)
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
    }


def format_initial_intake_prompt() -> str:
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


def _pick_exhaustiveness(
    cpu_count: int,
    time_budget_hours: int | None,
) -> int:
    """Choose exhaustiveness from {8, 16, 32} based on CPU budget.

    Paper default is 8 (Vina default). Only escalate when the user has lots
    of CPU-hours to spend.
    """
    budget = time_budget_hours if time_budget_hours is not None else 4
    capacity = cpu_count * budget
    if capacity >= 64:
        return 32
    if capacity >= 16:
        return 16
    return 8


def default_top_k(
    candidate_count: int,
    machine_profile: dict[str, Any],
    time_budget_hours: int | None,
) -> int:
    """Compute a sensible default top-k.

    Paper used 5 (Aptamers-2026.5.4.docx \u00a72.4.4). We honor that as the
    default unless the user supplies an explicit ``time_budget_hours`` that
    leaves room to dock more candidates, in which case we scale up but cap
    at ``candidate_count``.
    """
    if candidate_count <= 0:
        return 0
    paper_default = 5
    if time_budget_hours is None:
        return min(candidate_count, paper_default)
    cpu_count = coerce_int(machine_profile.get("cpu_count")) or 1
    rough_capacity = cpu_count * max(time_budget_hours, 1) * 4
    return max(1, min(candidate_count, max(paper_default, rough_capacity)))


def default_time_budget_hours(
    candidate_count: int,
    machine_profile: dict[str, Any],
    recommended_top_k: int,
    user_time_budget_hours: int | None,
) -> int:
    if user_time_budget_hours is not None:
        return max(user_time_budget_hours, 1)
    cpu_count = coerce_int(machine_profile.get("cpu_count")) or 1
    target = max(recommended_top_k or candidate_count or 1, 1)
    estimated = (target + (cpu_count * 4) - 1) // (cpu_count * 4)
    return max(1, min(24, estimated or 1))


def compute_deterministic_docking_plan(
    *,
    candidate_count: int,
    machine_profile: dict[str, Any],
    time_budget_hours: int | None,
    target_smiles: str | None = None,
) -> dict[str, Any]:
    """Return the deterministic docking plan (top_k / time / exhaustiveness).

    The grid box is no longer part of this plan: the box is computed per
    aptamer at preparation time to cover the entire structure.
    ``target_smiles`` is accepted for API compatibility but unused here.
    """
    del target_smiles
    top_k = default_top_k(candidate_count, machine_profile, time_budget_hours)
    recommended_time_budget = default_time_budget_hours(
        candidate_count,
        machine_profile,
        top_k,
        time_budget_hours,
    )
    cpu_count = coerce_int(machine_profile.get("cpu_count")) or 1
    exhaustiveness = _pick_exhaustiveness(cpu_count, time_budget_hours)
    return {
        "recommended_top_k": top_k,
        "recommended_time_budget_hours": recommended_time_budget,
        "recommended_exhaustiveness": exhaustiveness,
    }


def _clamp_exhaustiveness(value: Any) -> int | None:
    """Return *value* if it is one of {8, 16, 32}, else None."""
    v = coerce_int(value)
    if v in (8, 16, 32):
        return v
    return None


def validate_docking_recommendation_result(
    result: Any,
    *,
    candidate_count: int,
    machine_profile: dict[str, Any],
    time_budget_hours: int | None,
    target_smiles: str | None = None,
) -> dict[str, Any]:
    """Take LLM suggestion if sane, else fall back to deterministic defaults.

    Clamp rules:
    - ``top_k`` must be in ``[1, candidate_count]``
    - ``exhaustiveness`` must be in ``{8, 16, 32}``

    The grid box is no longer LLM-driven (it covers the entire aptamer per
    Aptamers-2026.5.4.docx §2.4.4), so any ``recommended_grid_size`` field
    in the LLM output is silently ignored.
    """
    plan = compute_deterministic_docking_plan(
        candidate_count=candidate_count,
        machine_profile=machine_profile,
        time_budget_hours=time_budget_hours,
        target_smiles=target_smiles,
    )
    llm_obj = result if isinstance(result, dict) else {}

    llm_top_k = coerce_int(llm_obj.get("recommended_top_k"))
    if llm_top_k is not None and 1 <= llm_top_k <= max(candidate_count, 1):
        top_k = llm_top_k
    else:
        top_k = plan["recommended_top_k"]

    llm_exh = _clamp_exhaustiveness(llm_obj.get("recommended_exhaustiveness"))
    exhaustiveness = llm_exh if llm_exh is not None else plan["recommended_exhaustiveness"]

    receptor_path_note = clean_text(llm_obj.get("receptor_path_note")) or (
        "Choose how each candidate's receptor PDBQT will be prepared: "
        "manual upload or RNAComposer auto-generation."
    )
    grid_center_note = clean_text(llm_obj.get("grid_center_note")) or (
        "The docking search box auto-covers each aptamer (bbox + 4 Å padding); "
        "no manual grid center is required."
    )
    reason = clean_text(llm_obj.get("reason")) or (
        "Using Vina defaults (num_modes=9, energy_range=3.0) on a "
        "conservative docking batch."
    )
    return {
        "recommended_time_budget_hours": plan["recommended_time_budget_hours"],
        "recommended_top_k": top_k,
        "recommended_exhaustiveness": exhaustiveness,
        "receptor_path_note": receptor_path_note,
        "grid_center_note": grid_center_note,
        "reason": reason,
    }


def validate_report_summary(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise RuntimeError("Invalid report summary response.")
    candidate_notes = result.get("candidate_notes")
    if not isinstance(candidate_notes, dict):
        candidate_notes = {}
    return {
        "summary": clean_text(result.get("summary")) or "",
        "candidate_notes": candidate_notes,
    }


def format_docking_recommendation_markdown(
    *,
    candidate_count: int,
    machine_profile: dict[str, Any],
    time_budget_hours: int | None,
    recommended_top_k: int,
    recommended_exhaustiveness: int | None = None,
    receptor_path_note: str = "",
    grid_center_note: str = "",
    reason: str = "",
) -> str:
    cpu_count = machine_profile.get("cpu_count", "?")
    memory_gb = machine_profile.get("memory_gb")
    memory_text = f"{memory_gb} GB" if memory_gb is not None else "unknown"
    budget_text = (
        f"{time_budget_hours} hour(s)"
        if time_budget_hours is not None
        else "not specified"
    )
    exh_text = str(recommended_exhaustiveness) if recommended_exhaustiveness is not None else "8 (Vina default)"
    return (
        f"{section_heading('Recommended Docking Setup')}\n\n"
        f"- Candidates available: **{candidate_count}**\n"
        f"- Time budget: **{budget_text}**\n"
        f"- Suggested batch: **top {recommended_top_k}**\n"
        f"- Exhaustiveness: **{exh_text}**\n"
        f"- Num modes: **9 (Vina default)**\n"
        f"- Energy range: **3.0 (Vina default)**\n"
        f"- Search box: covers the entire aptamer (bbox + 4 \u00c5 padding)\n"
        f"- Receptor prep: {receptor_path_note}\n"
        f"- Grid center: {grid_center_note}\n"
        f"- Machine profile: **{cpu_count} CPU(s)**, **{memory_text}** memory\n\n"
        f"- Rationale: {reason}"
    )
