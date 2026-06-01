from __future__ import annotations

from aptgent.domain.enums import Step
from aptgent.domain.models import (
    CandidateSequence,
    DockingResult,
    Mutation,
    PredictionResult,
    SpatialRankResult,
    SpecificityResult,
    TargetMolecule,
)
from aptgent.tui.steps.report import (
    build_report_context,
    export_final_report_artifacts,
    format_deterministic_report_markdown,
)
from aptgent.workflow.state import RunState
from aptgent.workflow.persistence import Persistence


def _candidate(candidate_id: str, sequence: str) -> CandidateSequence:
    return CandidateSequence(
        candidate_id=candidate_id,
        sequence=sequence,
        mutations=[Mutation(position=1, original="C", mutated="G")],
        edit_ratio=0.03,
    )


def _report_state() -> RunState:
    state = RunState(run_id="report_case")
    state.current_step = Step.FINAL_REPORT
    state.target_molecule = TargetMolecule(
        input_text="theophylline",
        resolved_name="Theophylline",
        smiles="Cn1cnc2[nH]cnc2c1=O",
        resolution_status="resolved",
    )
    state.candidates = [
        _candidate("cand_docked", "ACGUACGUACGU"),
        _candidate("cand_not_docked", "GGGGCCCCAAAA"),
        _candidate("cand_removed", "UUUUAAAACCCC"),
    ]
    state.predictions = [
        PredictionResult(
            candidate_id="cand_docked",
            model_name="ensemble",
            target="theophylline",
            score=0.92,
            label=1,
            probability=0.92,
        ),
        PredictionResult(
            candidate_id="cand_not_docked",
            model_name="ensemble",
            target="theophylline",
            score=0.81,
            label=1,
            probability=0.81,
        ),
        PredictionResult(
            candidate_id="cand_removed",
            model_name="ensemble",
            target="theophylline",
            score=0.77,
            label=1,
            probability=0.77,
        ),
    ]
    state.specificity_results = [
        SpecificityResult(candidate_id="cand_docked", status="kept"),
        SpecificityResult(candidate_id="cand_not_docked", status="kept"),
        SpecificityResult(candidate_id="cand_removed", status="removed"),
    ]
    state.docking_results = [
        DockingResult(candidate_id="cand_docked", docking_score=-7.2, status="completed")
    ]
    state.spatial_ranks = [
        SpatialRankResult(
            candidate_id="cand_docked",
            spatial_score=0.64,
            detected_groups=["purine", "aromatic"],
            rank=1,
        )
    ]
    return state


def test_report_context_only_expands_docked_sequences():
    context = build_report_context(_report_state())

    assert [item["candidate_id"] for item in context["docking_candidates"]] == [
        "cand_docked"
    ]
    assert context["docking_candidates"][0]["sequence"] == "ACGUACGUACGU"
    assert context["screening_overview"]["non_docked_candidate_count"] == 2
    assert context["screening_overview"]["specificity_status_counts"] == {
        "kept": 1,
        "removed": 1,
    }


def test_fallback_markdown_summarizes_non_docked_without_listing_each_sequence():
    markdown = format_deterministic_report_markdown(build_report_context(_report_state()))

    assert markdown.startswith("# Final Report")
    assert "cand_docked" in markdown
    assert "ACGUACGUACGU" in markdown
    assert "Other Screened Candidates" in markdown
    assert "GGGGCCCCAAAA" not in markdown
    assert "UUUUAAAACCCC" not in markdown


def _specificity_gate_state() -> RunState:
    """Three docked candidates, one removed by the specificity filter."""
    state = RunState(run_id="gate_case")
    state.current_step = Step.FINAL_REPORT
    state.target_molecule = TargetMolecule(
        input_text="theophylline",
        resolved_name="Theophylline",
        smiles="Cn1cnc2[nH]cnc2c1=O",
        resolution_status="resolved",
    )
    state.candidates = [
        _candidate("cand_a", "ACGUACGUACGU"),
        _candidate("cand_b", "GGGGCCCCAAAA"),
        _candidate("cand_c", "UUUUAAAACCCC"),
    ]
    state.predictions = [
        PredictionResult(
            candidate_id=cid,
            model_name="ensemble",
            target="theophylline",
            score=0.9,
            label=1,
            probability=0.9,
        )
        for cid in ("cand_a", "cand_b", "cand_c")
    ]
    state.specificity_results = [
        SpecificityResult(candidate_id="cand_a", status="kept"),
        SpecificityResult(candidate_id="cand_b", status="kept"),
        SpecificityResult(candidate_id="cand_c", status="removed"),
    ]
    state.docking_results = [
        DockingResult(candidate_id="cand_a", docking_score=-7.2, status="completed"),
        DockingResult(candidate_id="cand_b", docking_score=-6.8, status="completed"),
        DockingResult(candidate_id="cand_c", docking_score=-6.5, status="completed"),
    ]
    state.spatial_ranks = [
        SpatialRankResult(candidate_id="cand_a", spatial_score=2, rank=1),
        SpatialRankResult(candidate_id="cand_b", spatial_score=1, rank=2),
    ]
    return state


def test_specificity_excluded_candidates_dropped_from_ranking():
    context = build_report_context(_specificity_gate_state())

    ids = [item["candidate_id"] for item in context["docking_candidates"]]
    assert ids == ["cand_a", "cand_b"]
    assert "cand_c" not in ids
    assert context["screening_overview"]["specificity_excluded_from_docked_count"] == 1


def _affinity_filter_report_state() -> RunState:
    """Three docked; two affinity-selected with spatial ranks; one reference-only."""
    state = RunState(run_id="affinity_report")
    state.current_step = Step.FINAL_REPORT
    state.target_molecule = TargetMolecule(
        input_text="theophylline",
        resolved_name="Theophylline",
        smiles="Cn1cnc2[nH]cnc2c1=O",
        resolution_status="resolved",
    )
    state.candidates = [
        _candidate("cand_a", "ACGUACGUACGU"),
        _candidate("cand_b", "GGGGCCCCAAAA"),
        _candidate("cand_c", "UUUUAAAACCCC"),
    ]
    state.predictions = [
        PredictionResult(
            candidate_id=cid,
            model_name="ensemble",
            target="theophylline",
            score=0.9,
            label=1,
            probability=0.9,
        )
        for cid in ("cand_a", "cand_b", "cand_c")
    ]
    state.affinity_selected_ids = ["cand_a", "cand_b"]
    state.specificity_results = [
        SpecificityResult(candidate_id="cand_a", status="kept"),
        SpecificityResult(candidate_id="cand_b", status="kept"),
    ]
    state.docking_results = [
        DockingResult(candidate_id="cand_a", docking_score=-8.0, status="completed"),
        DockingResult(candidate_id="cand_b", docking_score=-7.0, status="completed"),
        DockingResult(candidate_id="cand_c", docking_score=-5.0, status="completed"),
    ]
    state.spatial_ranks = [
        SpatialRankResult(candidate_id="cand_a", spatial_score=2, rank=1),
        SpatialRankResult(candidate_id="cand_b", spatial_score=1, rank=2),
    ]
    return state


def test_report_lists_all_docked_including_non_affinity_selected():
    context = build_report_context(_affinity_filter_report_state())

    ids = [item["candidate_id"] for item in context["docking_candidates"]]
    assert ids == ["cand_a", "cand_b", "cand_c"]
    by_id = {item["candidate_id"]: item for item in context["docking_candidates"]}
    assert by_id["cand_a"]["affinity_selected"] is True
    assert by_id["cand_b"]["affinity_selected"] is True
    assert by_id["cand_c"]["affinity_selected"] is False
    assert by_id["cand_c"]["specificity_status"] == "pending"
    assert by_id["cand_c"]["spatial_rank"] is None
    assert context["screening_overview"]["docked_candidate_count"] == 3
    assert context["screening_overview"]["affinity_selected_count"] == 2


def test_non_affinity_selected_docked_shown_in_markdown():
    markdown = format_deterministic_report_markdown(
        build_report_context(_affinity_filter_report_state())
    )
    assert "cand_c" in markdown
    assert "*(not affinity-selected)*" in markdown
    assert "1 docked candidate(s) were not selected by binding affinity" in markdown


def test_specificity_excluded_count_shown_in_markdown():
    markdown = format_deterministic_report_markdown(
        build_report_context(_specificity_gate_state())
    )
    assert "1 candidate(s) excluded by specificity filter" in markdown
    assert "UUUUAAAACCCC" not in markdown


def test_export_final_report_writes_markdown_and_structured_sidecar(tmp_path):
    state = _report_state()
    persistence = Persistence(tmp_path / "runs")
    persistence.init_run(state.run_id)

    md_path, json_path = export_final_report_artifacts(
        persistence,
        state,
        "# Final Report\n\nReport body.",
        build_report_context(state),
    )

    assert md_path.name == "final_report.md"
    assert md_path.read_text(encoding="utf-8").startswith("# Final Report")
    assert json_path.name == "final_report.json"
    assert '"docking_candidates"' in json_path.read_text(encoding="utf-8")
