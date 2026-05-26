from __future__ import annotations

from types import SimpleNamespace

from aptgent.domain.enums import Step
from aptgent.domain.models import (
    CandidateSequence,
    DockingPlan,
    DockingResult,
    GridBox,
    PredictionResult,
    TargetMolecule,
)
from aptgent.jobs.events import EventReader, EventWriter
from aptgent.jobs.runner import _JOB_RUNNERS, _run_docking, _run_enumeration, build_parser
from aptgent.workflow.persistence import Persistence


class _FakeMutationBatchAdapter:
    def __init__(self, *, cancel: bool = False) -> None:
        self.cancel = cancel

    def predict_mutation_batch(
        self,
        *,
        base_sequence,
        target,
        sites,
        progress_callback,
        result_callback,
        progress_every,
        cancel_event,
        timeout_seconds,
        skip_first,
        sub_batch_size=None,
    ):
        progress_callback(0, 4, {})
        if self.cancel:
            cancel_event.set()
            return
        result_callback(
            {
                "sequence": "AG",
                "probability": 0.91,
                "model_probabilities": [0.91],
            }
        )
        progress_callback(4, 4, {})


class _FakeVinaAdapter:
    exhaustiveness = 8
    num_modes = 9
    energy_range = 3.0

    def run_batch(
        self,
        *,
        candidates,
        target,
        receptor_paths,
        grid_boxes,
        work_dir,
        seed,
        per_ligand_timeout,
    ):
        return [
            DockingResult(
                candidate_id=candidates[0].candidate_id or "",
                docking_score=-5.5,
                status="completed",
            )
        ]


def _fake_config(tmp_path):
    return SimpleNamespace(
        tools={},
        workflow={
            "paths": {"runs_dir": str(tmp_path)},
            "enumeration": {
                "top_k_keep": 5,
                "sub_batch_size": 4,
                "progress_every": 1,
                "mutation_batch_timeout_seconds": 0,
            },
        },
    )


class TestJobRunnerCLI:
    def test_parser_accepts_run_job(self):
        parser = build_parser()
        args = parser.parse_args(["run-job", "run1", "candidate_enumeration"])
        assert args.run_id == "run1"
        assert args.step == "candidate_enumeration"
        assert args.foreground is False

    def test_parser_accepts_foreground(self):
        parser = build_parser()
        args = parser.parse_args(["run-job", "run1", "docking_run", "--foreground"])
        assert args.foreground is True

    def test_job_runners_registry_has_enum_and_docking(self):
        assert "candidate_enumeration" in _JOB_RUNNERS
        assert "docking_run" in _JOB_RUNNERS
        assert "specificity_filter" in _JOB_RUNNERS

    def test_job_runners_registry_only_has_known_steps(self):
        for step_name in _JOB_RUNNERS:
            assert step_name in (
                "candidate_enumeration",
                "specificity_filter",
                "docking_run",
            )


def test_enumeration_runner_normal_completion_finalizes_hits(tmp_path, monkeypatch):
    persistence = Persistence(runs_dir=tmp_path)
    state = persistence.init_run("enum_normal")
    state.current_step = Step.CANDIDATE_ENUMERATION
    state.input_payload["initial_sequence"] = "AA"
    state.target_molecule = TargetMolecule(
        input_text="benzene",
        smiles="C1=CC=CC=C1",
        resolution_status="resolved",
    )
    state.confirmed_mutation_sites = [1]
    persistence.save(state)

    monkeypatch.setattr("aptgent.jobs.runner.load_config", lambda: _fake_config(tmp_path))
    monkeypatch.setattr(
        "aptgent.bootstrap.container.create_prediction_adapter",
        lambda _tools_config: _FakeMutationBatchAdapter(),
    )

    events_path = persistence.job_events_file(state.run_id, "candidate_enumeration")
    writer = EventWriter(events_path)
    try:
        _run_enumeration(writer, state, persistence)
    finally:
        writer.close()

    events = list(EventReader(events_path).iter_events())
    done = events[-1]
    saved = persistence.load(state.run_id)

    assert done["type"] == "done"
    assert done["summary"]["hits"] == 1
    assert done["summary"]["kept"] == 1
    assert "cancelled" not in done["summary"]
    assert saved is not None
    assert [candidate.sequence for candidate in saved.candidates] == ["AG"]
    assert [prediction.probability for prediction in saved.predictions] == [0.91]


def test_enumeration_runner_cancelled_completion_does_not_finalize(tmp_path, monkeypatch):
    persistence = Persistence(runs_dir=tmp_path)
    state = persistence.init_run("enum_cancelled")
    state.current_step = Step.CANDIDATE_ENUMERATION
    state.input_payload["initial_sequence"] = "AA"
    state.target_molecule = TargetMolecule(
        input_text="benzene",
        smiles="C1=CC=CC=C1",
        resolution_status="resolved",
    )
    state.confirmed_mutation_sites = [1]
    persistence.save(state)

    monkeypatch.setattr("aptgent.jobs.runner.load_config", lambda: _fake_config(tmp_path))
    monkeypatch.setattr(
        "aptgent.bootstrap.container.create_prediction_adapter",
        lambda _tools_config: _FakeMutationBatchAdapter(cancel=True),
    )

    events_path = persistence.job_events_file(state.run_id, "candidate_enumeration")
    writer = EventWriter(events_path)
    try:
        _run_enumeration(writer, state, persistence)
    finally:
        writer.close()

    events = list(EventReader(events_path).iter_events())
    done = events[-1]
    saved = persistence.load(state.run_id)

    assert done["type"] == "done"
    assert done["summary"]["cancelled"] is True
    assert saved is not None
    assert saved.candidates == []
    assert saved.predictions == []


def test_docking_runner_normal_completion_is_not_cancelled(tmp_path, monkeypatch):
    persistence = Persistence(runs_dir=tmp_path)
    state = persistence.init_run("dock_normal")
    state.current_step = Step.DOCKING_RUN
    state.target_molecule = TargetMolecule(
        input_text="theophylline",
        smiles="CN1C2=C(C(=O)N(C1=O)C)NC=N2",
        resolution_status="resolved",
    )
    state.candidates = [CandidateSequence(sequence="AA", candidate_id="cand_0")]
    state.predictions = [
        PredictionResult(
            candidate_id="cand_0",
            model_name="ensemble",
            target="theophylline",
            score=0.9,
            label=1,
            probability=0.9,
        )
    ]
    state.docking_plan = DockingPlan(
        recommended_top_k=1,
        receptor_paths={"cand_0": str(tmp_path / "cand_0.pdbqt")},
        grid_boxes={
            "cand_0": GridBox(
                center=[0.0, 0.0, 0.0],
                size=[10.0, 10.0, 10.0],
            )
        },
    )
    persistence.save(state)

    monkeypatch.setattr("aptgent.jobs.runner.load_config", lambda: _fake_config(tmp_path))
    monkeypatch.setattr(
        "aptgent.bootstrap.container.create_vina_adapter",
        lambda _tools_config: _FakeVinaAdapter(),
    )

    events_path = persistence.job_events_file(state.run_id, "docking_run")
    writer = EventWriter(events_path)
    try:
        _run_docking(writer, state, persistence)
    finally:
        writer.close()

    events = list(EventReader(events_path).iter_events())
    done = events[-1]
    saved = persistence.load(state.run_id)

    assert done["type"] == "done"
    assert done["summary"]["completed"] == 1
    assert done["summary"]["cancelled"] is False
    assert saved is not None
    assert len(saved.docking_results) == 1
