from __future__ import annotations

from aptgent.domain.models import SecondaryStructure, TargetMolecule
from aptgent.workflow.context import (
    build_site_proposal_llm_context,
    build_run_overview,
    get_sequence,
    record_docking_recommendation_context,
    record_intake_context,
    record_specificity_recommendation_context,
    record_site_proposal_context,
)
from aptgent.workflow.state import RunState


def test_context_helpers_prefer_confirmed_facts():
    state = RunState(run_id="ctx_case")
    state.input_payload["initial_sequence"] = "AAAA"
    state.input_payload["user_text"] = "old note"

    record_intake_context(
        state,
        user_brief="Design a tighter caffeine binder",
        sequence="ACGU",
        target_text="caffeine",
        resolved_target=TargetMolecule(
            input_text="caffeine",
            resolved_name="Caffeine",
            smiles="Cn1cnc2n(C)c(=O)n(C)c(=O)c12",
            resolution_status="resolved",
        ),
        analogs=["theobromine"],
        time_budget_hours=4,
    )

    assert get_sequence(state) == "ACGU"
    assert build_run_overview(state) == "Caffeine | ACGU"
def test_build_site_proposal_llm_context_collects_extensible_context():
    state = RunState(run_id="site_ctx_case")
    state.input_payload["user_text"] = "Keep the loop flexible."
    state.time_budget = 3
    state.secondary_structure = SecondaryStructure(
        sequence="ACGUAC",
        dot_bracket="..(..)",
        mfe=-2.4,
        features={"length": 6, "source": "rnafold"},
    )
    record_intake_context(
        state,
        sequence="ACGUAC",
        target_text="caffeine",
        resolved_target=TargetMolecule(
            input_text="caffeine",
            resolved_name="Caffeine",
            smiles="Cn1cnc2n(C)c(=O)n(C)c(=O)c12",
            resolution_status="resolved",
        ),
        modification_region="loop region",
        analogs=["theobromine"],
        time_budget_hours=4,
    )
    record_site_proposal_context(
        state,
        proposed_sites=[2],
        extra_context={
            "structure_lookup": {
                "status": "available",
                "pdb_ids": ["1ABC"],
            }
        },
    )

    result = build_site_proposal_llm_context(state)

    assert result["sequence"] == "ACGUAC"
    assert result["secondary_structure"]["dot_bracket"] == "..(..)"
    assert result["secondary_structure"]["features"]["source"] == "rnafold"
    assert result["secondary_structure_context"]["source"] == "rnafold"
    assert result["target_molecule"]["label"] == "Caffeine"
    assert result["user_request"]["modification_region"] == "loop region"
    assert result["workflow_context"]["previous_proposed_sites"] == [2]
    assert result["extra_context"]["structure_lookup"]["pdb_ids"] == ["1ABC"]
def test_record_docking_recommendation_context_persists_reason():
    state = RunState(run_id="dock_ctx_case")

    record_docking_recommendation_context(
        state,
        candidate_count=48,
        machine_profile={"cpu_count": 8, "memory_gb": 32},
        time_budget_hours=4,
        recommended_time_budget_hours=4,
        recommended_top_k=12,
        recommended_exhaustiveness=16,
        receptor_path_note="Provide the receptor path manually.",
        grid_center_note="Confirm the grid center from the binding site.",
        reason="Fits the available CPU budget.",
        display_markdown="- Time budget: 4",
        strategy="llm",
        phase="awaiting_decision",
        accepted=True,
        sequences_export_dir="/tmp/seqs",
        structures_dir="/tmp/structs",
    )

    context = state.context.docking_recommendation
    assert context.recommended_time_budget_hours == 4
    assert context.recommended_top_k == 12
    assert context.recommended_exhaustiveness == 16
    assert context.recommended_grid_size == []
    assert context.display_markdown == "- Time budget: 4"
    assert context.strategy == "llm"
    assert context.phase == "awaiting_decision"
    assert context.reason == "Fits the available CPU budget."
    assert context.accepted is True
    assert context.sequences_export_dir == "/tmp/seqs"
    assert context.structures_dir == "/tmp/structs"
def test_record_specificity_recommendation_context_persists_names_and_phase():
    state = RunState(run_id="spec_ctx_case")

    record_specificity_recommendation_context(
        state,
        analog_names=[" theobromine ", "", "paraxanthine"],
        display_markdown="- theobromine",
        note="Close xanthine analogs.",
        phase="awaiting_decision",
        accepted=False,
    )

    context = state.context.specificity_recommendation
    assert context.analog_names == ["theobromine", "paraxanthine"]
    assert context.display_markdown == "- theobromine"
    assert context.note == "Close xanthine analogs."
    assert context.phase == "awaiting_decision"
    assert context.accepted is False
