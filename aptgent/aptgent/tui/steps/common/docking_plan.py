from __future__ import annotations

from typing import Any

from aptgent.domain.text_utils import clean_text

from .coercion import coerce_int


def _pick_exhaustiveness(
    cpu_count: int,
    time_budget_hours: int | None,
) -> int:
    """Choose exhaustiveness from {8, 16, 32} based on CPU budget."""
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
    """Compute a sensible default top-k."""
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
    """Return the deterministic docking plan (top_k / time / exhaustiveness)."""
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
    """Take LLM suggestion if sane, else fall back to deterministic defaults."""
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
    from . import section_heading
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
