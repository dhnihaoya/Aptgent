from __future__ import annotations

from typing import Any

from aptgent.domain.text_utils import clean_text

from .coercion import coerce_float, coerce_int

DEFAULT_NUM_MODES = 9
DEFAULT_ENERGY_RANGE = 3.0
DEFAULT_GRID_PADDING_ANGSTROM = 4.0
DEFAULT_PER_LIGAND_TIMEOUT_SECONDS = 1800

NUM_MODES_BOUNDS = (1, 20)
ENERGY_RANGE_BOUNDS = (0.5, 10.0)
PER_LIGAND_TIMEOUT_BOUNDS = (60, 7200)
GRID_PADDING_BOUNDS = (0.0, 20.0)
SEED_MIN = 0


def _clamp_int(value: Any, lo: int, hi: int) -> int | None:
    v = coerce_int(value)
    if v is None:
        return None
    return max(lo, min(hi, v))


def _clamp_float(value: Any, lo: float, hi: float) -> float | None:
    v = coerce_float(value)
    if v is None:
        return None
    return max(lo, min(hi, v))


def _clamp_num_modes(value: Any) -> int | None:
    return _clamp_int(value, *NUM_MODES_BOUNDS)


def _clamp_energy_range(value: Any) -> float | None:
    return _clamp_float(value, *ENERGY_RANGE_BOUNDS)


def _clamp_per_ligand_timeout(value: Any) -> int | None:
    return _clamp_int(value, *PER_LIGAND_TIMEOUT_BOUNDS)


def _clamp_grid_padding(value: Any) -> float | None:
    return _clamp_float(value, *GRID_PADDING_BOUNDS)


def _clamp_seed(value: Any) -> int | None:
    v = coerce_int(value)
    if v is None:
        return None
    return max(SEED_MIN, v)


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
    per_ligand_timeout_default: int | None = None,
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

    num_modes = _clamp_num_modes(llm_obj.get("recommended_num_modes"))
    if num_modes is None:
        num_modes = DEFAULT_NUM_MODES

    energy_range = _clamp_energy_range(llm_obj.get("recommended_energy_range"))
    if energy_range is None:
        energy_range = DEFAULT_ENERGY_RANGE

    grid_padding = _clamp_grid_padding(llm_obj.get("recommended_grid_padding_angstrom"))
    if grid_padding is None:
        grid_padding = DEFAULT_GRID_PADDING_ANGSTROM

    per_ligand_timeout = _clamp_per_ligand_timeout(
        llm_obj.get("recommended_per_ligand_timeout_seconds")
    )
    if per_ligand_timeout is None:
        per_ligand_timeout = (
            per_ligand_timeout_default
            if per_ligand_timeout_default is not None
            else DEFAULT_PER_LIGAND_TIMEOUT_SECONDS
        )

    seed = _clamp_seed(llm_obj.get("recommended_seed"))

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
        "recommended_num_modes": num_modes,
        "recommended_energy_range": energy_range,
        "recommended_grid_padding_angstrom": grid_padding,
        "recommended_per_ligand_timeout_seconds": per_ligand_timeout,
        "recommended_seed": seed,
        "receptor_path_note": receptor_path_note,
        "grid_center_note": grid_center_note,
        "reason": reason,
    }


def validate_docking_param_overrides(
    raw: Any,
    *,
    candidate_count: int,
) -> tuple[dict[str, Any], dict[str, str], str | None]:
    """Validate a partial dict of docking parameter overrides.

    Returns ``(applied, warnings, action)`` where:

    - ``applied`` only contains fields the caller explicitly mentioned
      (after clamping); unmentioned fields are absent so the panel can
      preserve its current values.
    - ``warnings`` maps each clamped field to a short human-readable note.
    - ``action`` is one of ``"apply" | "skip" | "use_llm_hint" |
      "use_defaults" | None`` (None means "no action requested").
    """
    if not isinstance(raw, dict):
        return {}, {}, None
    applied: dict[str, Any] = {}
    warnings: dict[str, str] = {}

    def _maybe_clamp(
        key: str,
        clamper,
        bounds: tuple[Any, Any] | None,
        label: str | None = None,
    ) -> None:
        if key not in raw or raw[key] is None:
            return
        clamped = clamper(raw[key])
        if clamped is None:
            warnings[key] = (
                f"{label or key}: ignored (could not interpret {raw[key]!r})."
            )
            return
        original = raw[key]
        original_num = coerce_float(original)
        clamped_num = coerce_float(clamped)
        if (
            original_num is not None
            and clamped_num is not None
            and abs(original_num - clamped_num) > 1e-9
        ):
            if bounds is not None:
                warnings[key] = (
                    f"{label or key}: clamped {original} -> {clamped} "
                    f"(allowed range {bounds[0]}-{bounds[1]})."
                )
            else:
                warnings[key] = f"{label or key}: clamped {original} -> {clamped}."
        applied[key] = clamped

    if "top_k" in raw and raw["top_k"] is not None:
        v = coerce_int(raw["top_k"])
        if v is None:
            warnings["top_k"] = (
                f"top_k: ignored (could not interpret {raw['top_k']!r})."
            )
        else:
            ceiling = max(candidate_count, 1)
            clamped = max(1, min(ceiling, v))
            if clamped != v:
                warnings["top_k"] = (
                    f"top_k: clamped {v} -> {clamped} (1..{ceiling})."
                )
            applied["top_k"] = clamped

    if "affinity_top_k" in raw and raw["affinity_top_k"] is not None:
        v = coerce_int(raw["affinity_top_k"])
        if v is None:
            warnings["affinity_top_k"] = (
                f"affinity_top_k: ignored (could not interpret {raw['affinity_top_k']!r})."
            )
        else:
            top_k_val = applied.get("top_k") or max(candidate_count, 1)
            clamped = max(1, min(top_k_val, v))
            if clamped != v:
                warnings["affinity_top_k"] = (
                    f"affinity_top_k: clamped {v} -> {clamped} (1..{top_k_val})."
                )
            applied["affinity_top_k"] = clamped

    if "exhaustiveness" in raw and raw["exhaustiveness"] is not None:
        clamped = _clamp_exhaustiveness(raw["exhaustiveness"])
        if clamped is None:
            warnings["exhaustiveness"] = (
                "exhaustiveness: ignored (must be one of 8, 16, 32)."
            )
        else:
            applied["exhaustiveness"] = clamped

    _maybe_clamp(
        "num_modes",
        _clamp_num_modes,
        NUM_MODES_BOUNDS,
        label="num_modes",
    )
    _maybe_clamp(
        "energy_range",
        _clamp_energy_range,
        ENERGY_RANGE_BOUNDS,
        label="energy_range",
    )
    _maybe_clamp(
        "per_ligand_timeout_seconds",
        _clamp_per_ligand_timeout,
        PER_LIGAND_TIMEOUT_BOUNDS,
        label="per_ligand_timeout_seconds",
    )
    _maybe_clamp(
        "grid_padding_angstrom",
        _clamp_grid_padding,
        GRID_PADDING_BOUNDS,
        label="grid_padding_angstrom",
    )

    if "time_budget_hours" in raw and raw["time_budget_hours"] is not None:
        v = coerce_int(raw["time_budget_hours"])
        if v is None or v < 0:
            warnings["time_budget_hours"] = (
                f"time_budget_hours: ignored ({raw['time_budget_hours']!r})."
            )
        else:
            applied["time_budget_hours"] = max(0, v)

    if "seed" in raw and raw["seed"] is not None:
        clamped = _clamp_seed(raw["seed"])
        if clamped is None:
            warnings["seed"] = f"seed: ignored ({raw['seed']!r})."
        else:
            applied["seed"] = clamped

    action_raw = raw.get("action")
    action: str | None = None
    if isinstance(action_raw, str):
        candidate = action_raw.strip().lower()
        if candidate in {"apply", "skip", "use_llm_hint", "use_defaults"}:
            action = candidate

    return applied, warnings, action


def format_docking_recommendation_markdown(
    *,
    candidate_count: int,
    machine_profile: dict[str, Any],
    time_budget_hours: int | None,
    recommended_top_k: int,
    recommended_exhaustiveness: int | None = None,
    recommended_num_modes: int | None = None,
    recommended_energy_range: float | None = None,
    recommended_grid_padding_angstrom: float | None = None,
    recommended_per_ligand_timeout_seconds: int | None = None,
    recommended_seed: int | None = None,
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
    num_modes_text = (
        str(recommended_num_modes)
        if recommended_num_modes is not None
        else f"{DEFAULT_NUM_MODES} (Vina default)"
    )
    energy_text = (
        f"{recommended_energy_range}"
        if recommended_energy_range is not None
        else f"{DEFAULT_ENERGY_RANGE} (Vina default)"
    )
    padding_text = (
        f"{recommended_grid_padding_angstrom} \u00c5"
        if recommended_grid_padding_angstrom is not None
        else f"{DEFAULT_GRID_PADDING_ANGSTROM} \u00c5 (default)"
    )
    timeout_text = (
        f"{recommended_per_ligand_timeout_seconds} s"
        if recommended_per_ligand_timeout_seconds is not None
        else f"{DEFAULT_PER_LIGAND_TIMEOUT_SECONDS} s (config default)"
    )
    seed_text = (
        f"{recommended_seed}" if recommended_seed is not None else "unset (Vina random)"
    )
    return (
        f"{section_heading('Recommended Docking Setup')}\n\n"
        f"- Candidates available: **{candidate_count}**\n"
        f"- Time budget: **{budget_text}**\n"
        f"- Suggested batch: **top {recommended_top_k}**\n"
        f"- Exhaustiveness: **{exh_text}**\n"
        f"- Num modes: **{num_modes_text}**\n"
        f"- Energy range: **{energy_text}**\n"
        f"- Grid padding: **{padding_text}**\n"
        f"- Per-ligand timeout: **{timeout_text}**\n"
        f"- Seed: **{seed_text}**\n"
        f"- Search box: covers the entire aptamer (bbox + padding)\n"
        f"- Receptor prep: {receptor_path_note}\n"
        f"- Grid center: {grid_center_note}\n"
        f"- Machine profile: **{cpu_count} CPU(s)**, **{memory_text}** memory\n\n"
        f"- Rationale: {reason}"
    )
