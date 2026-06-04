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
    resolved_target: TargetMolecule | None = None,
    analogs: list[str] | None = None,
    last_resolution_error: str | None = None,
    clear_resolution_error: bool = False,
    **fields: Any,
) -> None:
    context = state.context.intake
    # Remap caller-facing key to context attribute name
    if "target_text" in fields:
        fields["target_input"] = fields.pop("target_text")
    if resolved_target is not None:
        fields["target_label"] = (
            resolved_target.resolved_name or resolved_target.input_text
        )
    if last_resolution_error is not None:
        fields["last_resolution_error"] = last_resolution_error
    elif clear_resolution_error:
        context.last_resolution_error = None
    if analogs is not None:
        context.analogs = [text for item in analogs if (text := clean_text(item))]
    patch_context(
        context,
        fields,
        str_keys={
            "user_brief", "sequence", "target_input", "target_label",
            "modification_region", "last_resolution_error",
        },
        list_keys={"proposed_sites"},
    )


def record_pdb_intake_context(
    state: RunState,
    *,
    clear: bool = False,
    **fields: Any,
) -> None:
    context = state.context.pdb_intake
    if clear:
        reset = state.context.pdb_intake.__class__()
        state.context.pdb_intake = reset
        context = reset
    patch_context(
        context,
        fields,
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
    match_ids: list[str] | None = None,
    **fields: Any,
) -> None:
    context = state.context.secondary_structure
    if match_ids is not None:
        context.match_ids = [text for item in match_ids if (text := clean_text(item))]
    patch_context(
        context,
        fields,
        str_keys={"query_sequence", "downloaded_artifact_path", "note"},
    )


def record_site_proposal_context(
    state: RunState,
    *,
    proposals: list[dict[str, Any]] | None = None,
    llm_context: dict[str, Any] | None = None,
    extra_context: dict[str, Any] | None = None,
    **fields: Any,
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
        fields,
        str_keys={"reasoning", "confidence", "selection_source", "regeneration_reason", "site_preference"},
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
            "site_preference": proposal.site_preference,
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
    machine_profile: dict[str, Any],
    sequences_export_dir: str = "",
    structures_dir: str = "",
    **fields: Any,
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
        {**fields, **dirs},
        str_keys={"receptor_path_note", "grid_center_note"},
    )
    context.recommended_grid_size = []


def record_tertiary_structure_context(
    state: RunState,
    **fields: Any,
) -> None:
    patch_context(
        state.context.tertiary_structure,
        fields,
        str_keys={"provider", "receptor_source", "job_id", "result_path", "error"},
    )


def record_specificity_recommendation_context(
    state: RunState,
    *,
    analog_names: list[str] | None = None,
    **fields: Any,
) -> None:
    context = state.context.specificity_recommendation
    if analog_names is not None:
        context.analog_names = [
            text for item in analog_names if (text := clean_text(item))
        ]
    patch_context(
        context,
        fields,
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
