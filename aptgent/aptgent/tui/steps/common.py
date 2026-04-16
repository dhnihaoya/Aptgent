from __future__ import annotations

from typing import Any, Callable

from aptgent.adapters.pdb_analysis import normalize_pdb_id
from aptgent.domain.models import TargetMolecule
from aptgent.workflow.engine import TRANSITIONS


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
        "### Captured Intake Details",
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
    return {
        "proposed_sites": coerce_int_list(
            result.get("proposed_sites"),
            min_value=0,
            max_value=max(sequence_length - 1, 0),
        ),
        "reasoning": clean_text(result.get("reasoning")) or "Suggested from the current secondary-structure context.",
        "confidence": (clean_text(result.get("confidence")) or "unknown").lower(),
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
            "### Recommended Specificity Analogs\n\n"
            f"No strong analog recommendations were returned for **{heading_target}**."
        )

    lines = [
        "### Recommended Specificity Analogs",
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


def default_top_k(
    candidate_count: int,
    machine_profile: dict[str, Any],
    time_budget_hours: int | None,
) -> int:
    if candidate_count <= 0:
        return 0
    cpu_count = coerce_int(machine_profile.get("cpu_count")) or 1
    budget_hours = max(time_budget_hours or 1, 1)
    rough_capacity = cpu_count * budget_hours * 4
    return max(1, min(candidate_count, rough_capacity))


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
    return max(1, min(8, estimated or 1))


def validate_docking_recommendation_result(
    result: Any,
    *,
    candidate_count: int,
    machine_profile: dict[str, Any],
    time_budget_hours: int | None,
) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise RuntimeError("Invalid docking recommendation response.")
    top_k = coerce_int(result.get("recommended_top_k"))
    if top_k is None or top_k <= 0:
        top_k = default_top_k(candidate_count, machine_profile, time_budget_hours)
    top_k = min(top_k, candidate_count)
    recommended_time_budget = coerce_int(result.get("recommended_time_budget_hours"))
    if recommended_time_budget is None or recommended_time_budget <= 0:
        recommended_time_budget = default_time_budget_hours(
            candidate_count,
            machine_profile,
            top_k,
            time_budget_hours,
        )
    grid_size = coerce_float_list(result.get("recommended_grid_size"), exact_len=3)
    if not grid_size:
        grid_size = [20.0, 20.0, 20.0]
    receptor_path_note = clean_text(result.get("receptor_path_note")) or (
        "Provide the receptor PDBQT path from your prepared or downloaded tertiary-structure target."
    )
    grid_center_note = clean_text(result.get("grid_center_note")) or (
        "Confirm the grid center manually from the binding region before running docking."
    )
    reason = clean_text(result.get("reason")) or "Using a conservative docking batch size based on available resources."
    return {
        "recommended_time_budget_hours": recommended_time_budget,
        "recommended_top_k": top_k,
        "recommended_grid_size": grid_size,
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
    recommended_grid_size: list[float],
    receptor_path_note: str,
    grid_center_note: str,
    reason: str,
) -> str:
    cpu_count = machine_profile.get("cpu_count", "?")
    memory_gb = machine_profile.get("memory_gb")
    memory_text = f"{memory_gb} GB" if memory_gb is not None else "unknown"
    budget_text = (
        f"{time_budget_hours} hour(s)"
        if time_budget_hours is not None
        else "not specified"
    )
    return (
        "### Recommended Docking Setup\n\n"
        f"- Candidates available: **{candidate_count}**\n"
        f"- Time budget: **{budget_text}**\n"
        f"- Suggested batch: **top {recommended_top_k}**\n"
        f"- Suggested grid box size: **{', '.join(f'{value:.1f}' for value in recommended_grid_size)}**\n"
        f"- Receptor path: {receptor_path_note}\n"
        f"- Grid center: {grid_center_note}\n"
        f"- Machine profile: **{cpu_count} CPU(s)**, **{memory_text}** memory\n\n"
        f"- Rationale: {reason}"
    )
