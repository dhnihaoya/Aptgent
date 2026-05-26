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
