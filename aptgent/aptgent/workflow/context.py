from __future__ import annotations

from typing import Any, Iterable

from aptgent.domain.models import TargetMolecule
from aptgent.domain.text_utils import clean_text
from aptgent.workflow.state import RunState


def patch_context(
    ctx: Any,
    updates: dict[str, Any],
    *,
    str_keys: Iterable[str] = (),
    list_keys: Iterable[str] = (),
) -> None:
    """Apply *updates* to *ctx*, skipping None values.

    String-valued keys listed in *str_keys* are run through
    :func:`clean_text` before assignment.  Keys listed in
    *list_keys* are shallow-copied via ``list()``.
    """
    str_set = set(str_keys)
    list_set = set(list_keys)
    for k, v in updates.items():
        if v is None:
            continue
        if k in str_set and isinstance(v, str):
            v = clean_text(v)
        if k in list_set:
            v = list(v)
        setattr(ctx, k, v)


def get_sequence(state: RunState) -> str | None:
    return clean_text(state.context.intake.sequence) or clean_text(
        state.input_payload.get("initial_sequence")
    )


def get_target_label(state: RunState) -> str | None:
    if state.target_molecule is not None:
        resolved = state.target_molecule.resolved_name or state.target_molecule.input_text
        text = clean_text(resolved)
        if text:
            return text
    return (
        clean_text(state.context.intake.target_label)
        or clean_text(state.context.intake.target_input)
        or clean_text(state.input_payload.get("target_molecule"))
    )


def get_user_brief(state: RunState) -> str | None:
    return clean_text(state.context.intake.user_brief) or clean_text(
        state.input_payload.get("user_text")
    )


def record_intake_context(
    state: RunState,
    *,
    user_brief: str | None = None,
    sequence: str | None = None,
    target_text: str | None = None,
    resolved_target: TargetMolecule | None = None,
    modification_region: str | None = None,
    analogs: list[str] | None = None,
    proposed_sites: list[int] | None = None,
    time_budget_hours: int | None = None,
    phase: str | None = None,
    retry_count: int | None = None,
    last_resolution_error: str | None = None,
    clear_resolution_error: bool = False,
    resolved_once: bool | None = None,
) -> None:
    context = state.context.intake
    updates: dict[str, Any] = {
        "user_brief": user_brief,
        "sequence": sequence,
        "target_input": target_text,
        "modification_region": modification_region,
        "proposed_sites": proposed_sites,
        "time_budget_hours": time_budget_hours,
        "phase": phase,
        "retry_count": retry_count,
        "resolved_once": resolved_once,
    }
    if resolved_target is not None:
        updates["target_label"] = (
            resolved_target.resolved_name or resolved_target.input_text
        )
    if last_resolution_error is not None:
        updates["last_resolution_error"] = last_resolution_error
    elif clear_resolution_error:
        context.last_resolution_error = None
    if analogs is not None:
        context.analogs = [text for item in analogs if (text := clean_text(item))]
    patch_context(
        context,
        updates,
        str_keys={
            "user_brief", "sequence", "target_input", "target_label",
            "modification_region", "last_resolution_error",
        },
        list_keys={"proposed_sites"},
    )


def record_pdb_intake_context(
    state: RunState,
    *,
    pdb_id: str | None = None,
    input_mode: str | None = None,
    mixed_input_detected: bool | None = None,
    download_status: str | None = None,
    analysis_status: str | None = None,
    artifact_path: str | None = None,
    title: str | None = None,
    chains: list[Any] | None = None,
    ligands: list[Any] | None = None,
    recommended_chain_id: str | None = None,
    recommended_ligand_key: str | None = None,
    selected_chain_id: str | None = None,
    selected_ligand_key: str | None = None,
    user_sequence: str | None = None,
    derived_sequence: str | None = None,
    sequence_match_status: str | None = None,
    semantic_validation_status: str | None = None,
    semantic_note: str | None = None,
    review_category: str | None = None,
    review_target_match: str | None = None,
    review_confidence: str | None = None,
    needs_user_selection: bool | None = None,
    error: str | None = None,
    clear: bool = False,
) -> None:
    context = state.context.pdb_intake
    if clear:
        reset = state.context.pdb_intake.__class__()
        state.context.pdb_intake = reset
        context = reset
    patch_context(
        context,
        {
            "pdb_id": pdb_id,
            "input_mode": input_mode,
            "mixed_input_detected": mixed_input_detected,
            "download_status": download_status,
            "analysis_status": analysis_status,
            "artifact_path": artifact_path,
            "title": title,
            "chains": chains,
            "ligands": ligands,
            "recommended_chain_id": recommended_chain_id,
            "recommended_ligand_key": recommended_ligand_key,
            "selected_chain_id": selected_chain_id,
            "selected_ligand_key": selected_ligand_key,
            "user_sequence": user_sequence,
            "derived_sequence": derived_sequence,
            "sequence_match_status": sequence_match_status,
            "semantic_validation_status": semantic_validation_status,
            "semantic_note": semantic_note,
            "review_category": review_category,
            "review_target_match": review_target_match,
            "review_confidence": review_confidence,
            "needs_user_selection": needs_user_selection,
            "error": error,
        },
        str_keys={
            "pdb_id", "artifact_path", "title",
            "recommended_chain_id", "recommended_ligand_key",
            "selected_chain_id", "selected_ligand_key",
            "user_sequence", "derived_sequence", "semantic_note", "error",
        },
        list_keys={"chains", "ligands"},
    )


def record_secondary_structure_context(
    state: RunState,
    *,
    lookup_status: str | None = None,
    source: str | None = None,
    query_sequence: str | None = None,
    match_ids: list[str] | None = None,
    downloaded_artifact_path: str | None = None,
    note: str | None = None,
) -> None:
    context = state.context.secondary_structure
    if match_ids is not None:
        context.match_ids = [text for item in match_ids if (text := clean_text(item))]
    patch_context(
        context,
        {
            "lookup_status": lookup_status,
            "source": source,
            "query_sequence": query_sequence,
            "downloaded_artifact_path": downloaded_artifact_path,
            "note": note,
        },
        str_keys={"query_sequence", "downloaded_artifact_path", "note"},
    )


def record_site_proposal_context(
    state: RunState,
    *,
    proposals: list[dict[str, Any]] | None = None,
    proposed_sites: list[int] | None = None,
    reasoning: str | None = None,
    confidence: str | None = None,
    confirmed_sites: list[int] | None = None,
    llm_context: dict[str, Any] | None = None,
    extra_context: dict[str, Any] | None = None,
    selection_source: str | None = None,
    selected_proposal_index: int | None = None,
    needs_regeneration: bool | None = None,
    regeneration_reason: str | None = None,
    preserve_proposal_indexes: list[int] | None = None,
) -> None:
    context = state.context.site_proposal
    if proposals is not None:
        context.proposals = [dict(p) for p in proposals]
    if llm_context is not None:
        context.llm_context = dict(llm_context)
    if extra_context is not None:
        context.extra_context = dict(extra_context)
    patch_context(
        context,
        {
            "proposed_sites": proposed_sites,
            "reasoning": reasoning,
            "confidence": confidence,
            "confirmed_sites": confirmed_sites,
            "selection_source": selection_source,
            "selected_proposal_index": selected_proposal_index,
            "needs_regeneration": needs_regeneration,
            "regeneration_reason": regeneration_reason,
            "preserve_proposal_indexes": preserve_proposal_indexes,
        },
        str_keys={"reasoning", "confidence", "selection_source", "regeneration_reason"},
        list_keys={"proposed_sites", "confirmed_sites", "preserve_proposal_indexes"},
    )


def build_site_proposal_llm_context(state: RunState) -> dict[str, Any]:
    structure = state.secondary_structure
    target = state.target_molecule
    intake = state.context.intake
    proposal = state.context.site_proposal
    target_label = get_target_label(state)

    target_payload: dict[str, Any] = {
        "label": target_label,
    }
    if target is not None:
        target_payload.update(
            {
                "input_text": target.input_text,
                "resolved_name": target.resolved_name,
                "smiles": target.smiles,
                "resolution_status": target.resolution_status,
            }
        )
    elif target_label or intake.target_input:
        target_payload.update(
            {
                "input_text": intake.target_input,
                "resolved_name": intake.target_label,
                "smiles": None,
                "resolution_status": "pending_context_only",
            }
        )

    structure_payload: dict[str, Any] = {}
    if structure is not None:
        structure_payload = {
            "sequence": structure.sequence,
            "dot_bracket": structure.dot_bracket,
            "mfe_kcal_per_mol": structure.mfe,
            "features": dict(structure.features),
        }

    return {
        "sequence": get_sequence(state),
        "target_molecule": target_payload,
        "pdb_intake": {
            "pdb_id": state.context.pdb_intake.pdb_id,
            "input_mode": state.context.pdb_intake.input_mode,
            "selected_chain_id": state.context.pdb_intake.selected_chain_id,
            "selected_ligand_key": state.context.pdb_intake.selected_ligand_key,
            "sequence_match_status": state.context.pdb_intake.sequence_match_status,
            "semantic_validation_status": state.context.pdb_intake.semantic_validation_status,
        },
        "secondary_structure": structure_payload,
        "secondary_structure_context": {
            "lookup_status": state.context.secondary_structure.lookup_status,
            "source": state.context.secondary_structure.source,
            "match_ids": list(state.context.secondary_structure.match_ids),
            "downloaded_artifact_path": state.context.secondary_structure.downloaded_artifact_path,
            "note": state.context.secondary_structure.note,
        },
        "user_request": {
            "brief": get_user_brief(state),
            "modification_region": intake.modification_region,
            "analogs": list(intake.analogs),
            "time_budget_hours": intake.time_budget_hours or state.time_budget,
        },
        "workflow_context": {
            "current_step": state.current_step.value,
            "previous_site_proposals": list(proposal.proposals),
            "previous_proposed_sites": list(proposal.proposed_sites),
            "confirmed_mutation_sites": list(state.confirmed_mutation_sites),
        },
        "tertiary_structure_context": {
            "provider": state.context.tertiary_structure.provider,
            "receptor_source": state.context.tertiary_structure.receptor_source,
            "receptor_status": state.context.tertiary_structure.receptor_status,
            "job_id": state.context.tertiary_structure.job_id,
            "result_path": state.context.tertiary_structure.result_path,
        },
        "extra_context": dict(proposal.extra_context),
    }


def record_docking_recommendation_context(
    state: RunState,
    *,
    candidate_count: int,
    machine_profile: dict[str, Any],
    time_budget_hours: int | None,
    recommended_time_budget_hours: int | None,
    recommended_top_k: int,
    recommended_exhaustiveness: int | None = None,
    recommended_num_modes: int | None = None,
    recommended_energy_range: float | None = None,
    recommended_per_ligand_timeout_seconds: int | None = None,
    recommended_grid_padding_angstrom: float | None = None,
    recommended_seed: int | None = None,
    receptor_path_note: str = "",
    grid_center_note: str = "",
    reason: str = "",
    display_markdown: str = "",
    strategy: str = "",
    phase: str = "initial",
    accepted: bool = False,
    sequences_export_dir: str = "",
    structures_dir: str = "",
) -> None:
    context = state.context.docking_recommendation
    context.machine_profile = dict(machine_profile)
    dirs: dict[str, Any] = {}
    if sequences_export_dir:
        dirs["sequences_export_dir"] = sequences_export_dir
    if structures_dir:
        dirs["structures_dir"] = structures_dir
    patch_context(
        context,
        {
            "candidate_count": candidate_count,
            "time_budget_hours": time_budget_hours,
            "recommended_time_budget_hours": recommended_time_budget_hours,
            "recommended_top_k": recommended_top_k,
            "recommended_exhaustiveness": recommended_exhaustiveness,
            "recommended_num_modes": recommended_num_modes,
            "recommended_energy_range": recommended_energy_range,
            "recommended_per_ligand_timeout_seconds": (
                recommended_per_ligand_timeout_seconds
            ),
            "recommended_grid_padding_angstrom": recommended_grid_padding_angstrom,
            "recommended_seed": recommended_seed,
            "receptor_path_note": receptor_path_note,
            "grid_center_note": grid_center_note,
            "reason": reason,
            "display_markdown": display_markdown,
            "strategy": strategy,
            "phase": phase,
            "accepted": accepted,
            **dirs,
        },
        str_keys={"receptor_path_note", "grid_center_note"},
    )
    context.recommended_grid_size = []


def record_tertiary_structure_context(
    state: RunState,
    *,
    provider: str | None = None,
    receptor_source: str | None = None,
    receptor_status: str | None = None,
    job_id: str | None = None,
    result_path: str | None = None,
    error: str | None = None,
) -> None:
    patch_context(
        state.context.tertiary_structure,
        {
            "provider": provider,
            "receptor_source": receptor_source,
            "receptor_status": receptor_status,
            "job_id": job_id,
            "result_path": result_path,
            "error": error,
        },
        str_keys={"provider", "receptor_source", "job_id", "result_path", "error"},
    )


def record_specificity_recommendation_context(
    state: RunState,
    *,
    analog_names: list[str] | None = None,
    display_markdown: str = "",
    note: str = "",
    phase: str = "initial",
    accepted: bool = False,
) -> None:
    context = state.context.specificity_recommendation
    if analog_names is not None:
        context.analog_names = [
            text for item in analog_names if (text := clean_text(item))
        ]
    patch_context(
        context,
        {
            "display_markdown": display_markdown,
            "note": note,
            "phase": phase,
            "accepted": accepted,
        },
        str_keys={"note"},
    )


def build_run_overview(state: RunState) -> str:
    target = get_target_label(state)
    sequence = get_sequence(state)
    user_brief = get_user_brief(state)

    parts: list[str] = []
    if target:
        parts.append(target)
    if sequence:
        parts.append(sequence)
    elif user_brief:
        parts.append(user_brief)
    return " | ".join(parts) if parts else "Untitled run"
