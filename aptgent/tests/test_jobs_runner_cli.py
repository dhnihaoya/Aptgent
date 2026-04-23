from __future__ import annotations

from types import SimpleNamespace

from aptgent.domain.enums import Step
from aptgent.domain.models import TargetMolecule
from aptgent.jobs.events import EventReader, EventWriter
from aptgent.jobs.runner import _JOB_RUNNERS, _run_enumeration, build_parser
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

    def test_job_runners_registry_only_has_known_steps(self):
        for step_name in _JOB_RUNNERS:
            assert step_name in ("candidate_enumeration", "docking_run")


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
