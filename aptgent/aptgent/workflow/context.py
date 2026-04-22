from __future__ import annotations

from typing import Any

from aptgent.domain.models import TargetMolecule
from aptgent.workflow.state import RunState


def _clean_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = " ".join(value.split())
    return value or None


def get_sequence(state: RunState) -> str | None:
    return _clean_text(state.context.intake.sequence) or _clean_text(
        state.input_payload.get("initial_sequence")
    )


def get_target_label(state: RunState) -> str | None:
    if state.target_molecule is not None:
        resolved = state.target_molecule.resolved_name or state.target_molecule.input_text
        text = _clean_text(resolved)
        if text:
            return text
    return (
        _clean_text(state.context.intake.target_label)
        or _clean_text(state.context.intake.target_input)
        or _clean_text(state.input_payload.get("target_molecule"))
    )


def get_user_brief(state: RunState) -> str | None:
    return _clean_text(state.context.intake.user_brief) or _clean_text(
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
    time_budget_hours: int | None = None,
    phase: str | None = None,
    retry_count: int | None = None,
    last_resolution_error: str | None = None,
    clear_resolution_error: bool = False,
    resolved_once: bool | None = None,
) -> None:
    context = state.context.intake
    if user_brief is not None:
        context.user_brief = _clean_text(user_brief)
    if sequence is not None:
        context.sequence = _clean_text(sequence)
    if target_text is not None:
        context.target_input = _clean_text(target_text)
    if resolved_target is not None:
        context.target_label = _clean_text(
            resolved_target.resolved_name or resolved_target.input_text
        )
    if modification_region is not None:
        context.modification_region = _clean_text(modification_region)
    if analogs is not None:
        context.analogs = [text for item in analogs if (text := _clean_text(item))]
    if time_budget_hours is not None:
        context.time_budget_hours = time_budget_hours
    if phase is not None:
        context.phase = phase
    if retry_count is not None:
        context.retry_count = retry_count
    if last_resolution_error is not None:
        context.last_resolution_error = _clean_text(last_resolution_error)
    elif clear_resolution_error:
        context.last_resolution_error = None
    if resolved_once is not None:
        context.resolved_once = resolved_once


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
    if pdb_id is not None:
        context.pdb_id = _clean_text(pdb_id)
    if input_mode is not None:
        context.input_mode = input_mode
    if mixed_input_detected is not None:
        context.mixed_input_detected = mixed_input_detected
    if download_status is not None:
        context.download_status = download_status
    if analysis_status is not None:
        context.analysis_status = analysis_status
    if artifact_path is not None:
        context.artifact_path = _clean_text(artifact_path)
    if title is not None:
        context.title = _clean_text(title)
    if chains is not None:
        context.chains = list(chains)
    if ligands is not None:
        context.ligands = list(ligands)
    if recommended_chain_id is not None:
        context.recommended_chain_id = _clean_text(recommended_chain_id)
    if recommended_ligand_key is not None:
        context.recommended_ligand_key = _clean_text(recommended_ligand_key)
    if selected_chain_id is not None:
        context.selected_chain_id = _clean_text(selected_chain_id)
    if selected_ligand_key is not None:
        context.selected_ligand_key = _clean_text(selected_ligand_key)
    if user_sequence is not None:
        context.user_sequence = _clean_text(user_sequence)
    if derived_sequence is not None:
        context.derived_sequence = _clean_text(derived_sequence)
    if sequence_match_status is not None:
        context.sequence_match_status = sequence_match_status
    if semantic_validation_status is not None:
        context.semantic_validation_status = semantic_validation_status
    if semantic_note is not None:
        context.semantic_note = _clean_text(semantic_note)
    if review_category is not None:
        context.review_category = review_category
    if review_target_match is not None:
        context.review_target_match = review_target_match
    if review_confidence is not None:
        context.review_confidence = review_confidence
    if needs_user_selection is not None:
        context.needs_user_selection = needs_user_selection
    if error is not None:
        context.error = _clean_text(error)


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
    if lookup_status is not None:
        context.lookup_status = lookup_status
    if source is not None:
        context.source = source
    if query_sequence is not None:
        context.query_sequence = _clean_text(query_sequence)
    if match_ids is not None:
        context.match_ids = [text for item in match_ids if (text := _clean_text(item))]
    if downloaded_artifact_path is not None:
        context.downloaded_artifact_path = _clean_text(downloaded_artifact_path)
    if note is not None:
        context.note = _clean_text(note)


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
) -> None:
    context = state.context.site_proposal
    if proposals is not None:
        context.proposals = [dict(proposal) for proposal in proposals]
    if proposed_sites is not None:
        context.proposed_sites = list(proposed_sites)
    if reasoning is not None:
        context.reasoning = _clean_text(reasoning)
    if confidence is not None:
        context.confidence = _clean_text(confidence)
    if confirmed_sites is not None:
        context.confirmed_sites = list(confirmed_sites)
    if llm_context is not None:
        context.llm_context = dict(llm_context)
    if extra_context is not None:
        context.extra_context = dict(extra_context)


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
    recommended_grid_size: list[float] | None,
    recommended_exhaustiveness: int | None = None,
    receptor_path_note: str = "",
    grid_center_note: str = "",
    reason: str = "",
    display_markdown: str = "",
    strategy: str = "",
    phase: str = "initial",
    accepted: bool = False,
) -> None:
    context = state.context.docking_recommendation
    context.candidate_count = candidate_count
    context.machine_profile = dict(machine_profile)
    context.time_budget_hours = time_budget_hours
    context.recommended_time_budget_hours = recommended_time_budget_hours
    context.recommended_top_k = recommended_top_k
    context.recommended_grid_size = list(recommended_grid_size or [])
    context.recommended_exhaustiveness = recommended_exhaustiveness
    context.receptor_path_note = _clean_text(receptor_path_note) or ""
    context.grid_center_note = _clean_text(grid_center_note) or ""
    context.reason = reason
    context.display_markdown = display_markdown
    context.strategy = strategy
    context.phase = phase
    context.accepted = accepted


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
    context = state.context.tertiary_structure
    if provider is not None:
        context.provider = _clean_text(provider)
    if receptor_source is not None:
        context.receptor_source = _clean_text(receptor_source)
    if receptor_status is not None:
        context.receptor_status = receptor_status
    if job_id is not None:
        context.job_id = _clean_text(job_id)
    if result_path is not None:
        context.result_path = _clean_text(result_path)
    if error is not None:
        context.error = _clean_text(error)


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
    context.analog_names = [
        text for item in (analog_names or []) if (text := _clean_text(item))
    ]
    context.display_markdown = display_markdown
    context.note = _clean_text(note) or ""
    context.phase = phase
    context.accepted = accepted


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
