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
from aptgent.jobs.runner.docking import _dock_candidate_ids
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
        cancel_event=None,
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
                "num_models": 1,
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

    monkeypatch.setattr("aptgent.jobs.runner.enumeration.load_config", lambda: _fake_config(tmp_path))
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

    monkeypatch.setattr("aptgent.jobs.runner.enumeration.load_config", lambda: _fake_config(tmp_path))
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

    monkeypatch.setattr("aptgent.jobs.runner.docking.load_config", lambda: _fake_config(tmp_path))
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


def test_dock_candidate_ids_uses_receptor_paths_not_raw_top_k():
    """Dock list must follow prepared receptors, not blind ensemble top-k."""
    candidates = [
        CandidateSequence(sequence="s0", candidate_id=f"cand_{i}")
        for i in range(10)
    ]
    predictions = [
        PredictionResult(
            candidate_id=f"cand_{i}",
            model_name="ensemble",
            target="t",
            score=0.9 - i * 0.01,
            label=1,
            probability=0.9 - i * 0.01,
            raw_outputs={"cumulative_rank": i + 1},
        )
        for i in range(10)
    ]
    # Structure prep kept mutation-filtered set (skips cand_1, cand_5, cand_8).
    plan = DockingPlan(
        recommended_top_k=7,
        receptor_paths={
            f"cand_{i}": f"/tmp/cand_{i}.pdbqt"
            for i in (0, 2, 3, 4, 6, 7, 9)
        },
    )
    state = SimpleNamespace(
        candidates=candidates,
        predictions=predictions,
        docking_plan=plan,
    )

    dock_ids = _dock_candidate_ids(state, plan)

    assert dock_ids == ["cand_0", "cand_2", "cand_3", "cand_4", "cand_6", "cand_7", "cand_9"]
    assert "cand_1" not in dock_ids
    assert "cand_5" not in dock_ids


def test_docking_runner_skips_candidates_without_receptors(tmp_path, monkeypatch):
    """Runner must not emit missing_receptor for unprepared candidates."""
    persistence = Persistence(runs_dir=tmp_path)
    state = persistence.init_run("dock_receptor_aligned")
    state.current_step = Step.DOCKING_RUN
    state.target_molecule = TargetMolecule(
        input_text="theophylline",
        smiles="CN1C2=C(C(=O)N(C1=O)C)NC=N2",
        resolution_status="resolved",
    )
    state.candidates = [
        CandidateSequence(sequence=f"s{i}", candidate_id=f"cand_{i}")
        for i in range(7)
    ]
    state.predictions = [
        PredictionResult(
            candidate_id=f"cand_{i}",
            model_name="ensemble",
            target="theophylline",
            score=0.9,
            label=1,
            probability=0.9,
            raw_outputs={"cumulative_rank": i + 1},
        )
        for i in range(7)
    ]
    prepared = ("cand_0", "cand_2", "cand_3", "cand_4", "cand_6")
    state.docking_plan = DockingPlan(
        recommended_top_k=7,
        receptor_paths={
            cid: str(tmp_path / f"{cid}.pdbqt") for cid in prepared
        },
        grid_boxes={
            cid: GridBox(center=[0.0, 0.0, 0.0], size=[10.0, 10.0, 10.0])
            for cid in prepared
        },
    )
    persistence.save(state)

    docked_ids: list[str] = []

    class _TrackingVinaAdapter(_FakeVinaAdapter):
        def run_batch(self, *, candidates, **kwargs):
            docked_ids.append(candidates[0].candidate_id or "")
            return super().run_batch(candidates=candidates, **kwargs)

    monkeypatch.setattr("aptgent.jobs.runner.docking.load_config", lambda: _fake_config(tmp_path))
    monkeypatch.setattr(
        "aptgent.bootstrap.container.create_vina_adapter",
        lambda _tools_config: _TrackingVinaAdapter(),
    )

    events_path = persistence.job_events_file(state.run_id, "docking_run")
    writer = EventWriter(events_path)
    try:
        _run_docking(writer, state, persistence)
    finally:
        writer.close()

    saved = persistence.load(state.run_id)
    assert saved is not None
    assert docked_ids == list(prepared)
    assert all(r.status != "missing_receptor" for r in saved.docking_results)
    assert {r.candidate_id for r in saved.docking_results} == set(prepared)


class _FakeMultiModelAdapter:
    """Returns multiple candidates with different model_probabilities."""

    def __init__(self, results: list[dict]) -> None:
        self._results = results

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
        total = len(self._results)
        progress_callback(0, total, {})
        for r in self._results:
            result_callback(r)
        progress_callback(total, total, {})


def _multi_model_config(tmp_path, num_models=3):
    return SimpleNamespace(
        tools={},
        workflow={
            "paths": {"runs_dir": str(tmp_path)},
            "enumeration": {
                "top_k_keep": 10,
                "sub_batch_size": 4,
                "progress_every": 1,
                "mutation_batch_timeout_seconds": 0,
                "num_models": num_models,
            },
        },
    )


def test_enumeration_finalize_rank_sum_ordering_differs_from_mean_prob(tmp_path, monkeypatch):
    """Verify that rank-sum ordering produces different results than mean-prob
    when a candidate has inconsistent model scores."""
    # 3 models, 3 candidates:
    #   A: [0.9, 0.3, 0.3] → mean=0.5, rank_sum = 1+3+3 = 7
    #   B: [0.5, 0.5, 0.5] → mean=0.5, rank_sum = 2+2+2 = 6 (better!)
    #   C: [0.1, 0.9, 0.9] → mean≈0.633, rank_sum = 3+1+1 = 5 (best by rank-sum)
    results = [
        {"sequence": "AG", "probability": 0.5, "model_probabilities": [0.9, 0.3, 0.3]},
        {"sequence": "TG", "probability": 0.5, "model_probabilities": [0.5, 0.5, 0.5]},
        {"sequence": "GG", "probability": 0.633, "model_probabilities": [0.1, 0.9, 0.9]},
    ]
    adapter = _FakeMultiModelAdapter(results)

    persistence = Persistence(runs_dir=tmp_path)
    state = persistence.init_run("rank_sum_test")
    state.current_step = Step.CANDIDATE_ENUMERATION
    state.input_payload["initial_sequence"] = "AA"
    state.target_molecule = TargetMolecule(
        input_text="test",
        smiles="C",
        resolution_status="resolved",
    )
    state.confirmed_mutation_sites = [1]
    persistence.save(state)

    monkeypatch.setattr("aptgent.jobs.runner.enumeration.load_config", lambda: _multi_model_config(tmp_path))
    monkeypatch.setattr(
        "aptgent.bootstrap.container.create_prediction_adapter",
        lambda _tools_config: adapter,
    )

    events_path = persistence.job_events_file(state.run_id, "candidate_enumeration")
    writer = EventWriter(events_path)
    try:
        _run_enumeration(writer, state, persistence)
    finally:
        writer.close()

    saved = persistence.load(state.run_id)

    # Order should be: C (rank_sum=5), B (rank_sum=6), A (rank_sum=7)
    assert [c.sequence for c in saved.candidates] == ["GG", "TG", "AG"]
    # cumulative_rank is 1-based
    assert [p.raw_outputs["cumulative_rank"] for p in saved.predictions] == [1, 2, 3]
    assert [p.raw_outputs["rank_sum"] for p in saved.predictions] == [5, 6, 7]
    # probability is average of model probabilities (display score)
    assert [round(p.probability, 3) for p in saved.predictions] == [0.633, 0.5, 0.5]


def test_enumeration_finalize_uses_rank_probabilities_for_dense_rank(tmp_path, monkeypatch):
    """Display probabilities may tie after rounding, but rank probabilities must not."""
    results = [
        {
            "sequence": "AG",
            "probability": 0.9,
            "model_probabilities": [0.9],
            "rank_probabilities": [0.90000041],
        },
        {
            "sequence": "TG",
            "probability": 0.9,
            "model_probabilities": [0.9],
            "rank_probabilities": [0.90000049],
        },
        {
            "sequence": "GG",
            "probability": 0.9,
            "model_probabilities": [0.9],
            "rank_probabilities": [0.89999951],
        },
    ]
    adapter = _FakeMultiModelAdapter(results)

    persistence = Persistence(runs_dir=tmp_path)
    state = persistence.init_run("rank_precision_test")
    state.current_step = Step.CANDIDATE_ENUMERATION
    state.input_payload["initial_sequence"] = "AA"
    state.target_molecule = TargetMolecule(
        input_text="test",
        smiles="C",
        resolution_status="resolved",
    )
    state.confirmed_mutation_sites = [1]
    persistence.save(state)

    monkeypatch.setattr("aptgent.jobs.runner.enumeration.load_config", lambda: _multi_model_config(tmp_path, num_models=1))
    monkeypatch.setattr(
        "aptgent.bootstrap.container.create_prediction_adapter",
        lambda _tools_config: adapter,
    )

    events_path = persistence.job_events_file(state.run_id, "candidate_enumeration")
    writer = EventWriter(events_path)
    try:
        _run_enumeration(writer, state, persistence)
    finally:
        writer.close()

    saved = persistence.load(state.run_id)

    assert [c.sequence for c in saved.candidates] == ["TG", "AG", "GG"]
    assert [p.raw_outputs["rank_sum"] for p in saved.predictions] == [1, 2, 3]
    assert [p.raw_outputs["cumulative_rank"] for p in saved.predictions] == [1, 2, 3]
    assert [p.raw_outputs["model_probabilities"] for p in saved.predictions] == [
        [0.9],
        [0.9],
        [0.9],
    ]


def test_enumeration_finalize_skips_mismatched_model_count(tmp_path, monkeypatch):
    """Candidates with wrong model_probabilities length are skipped."""
    results = [
        {"sequence": "AG", "probability": 0.8, "model_probabilities": [0.8, 0.8, 0.8]},
        {"sequence": "TG", "probability": 0.5, "model_probabilities": [0.5]},  # wrong length
    ]
    adapter = _FakeMultiModelAdapter(results)

    persistence = Persistence(runs_dir=tmp_path)
    state = persistence.init_run("skip_test")
    state.current_step = Step.CANDIDATE_ENUMERATION
    state.input_payload["initial_sequence"] = "AA"
    state.target_molecule = TargetMolecule(
        input_text="test",
        smiles="C",
        resolution_status="resolved",
    )
    state.confirmed_mutation_sites = [1]
    persistence.save(state)

    monkeypatch.setattr("aptgent.jobs.runner.enumeration.load_config", lambda: _multi_model_config(tmp_path))
    monkeypatch.setattr(
        "aptgent.bootstrap.container.create_prediction_adapter",
        lambda _tools_config: adapter,
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

    assert done["summary"]["hits"] == 2
    assert done["summary"]["kept"] == 1
    assert done["summary"]["skipped_mismatched_models"] == 1
    assert [c.sequence for c in saved.candidates] == ["AG"]
