from __future__ import annotations

import json
from types import SimpleNamespace

from aptgent.domain.enums import Step
from aptgent.domain.models import CandidateSequence, TargetMolecule
from aptgent.jobs.events import EventReader, EventWriter
from aptgent.jobs.runner import _run_specificity
from aptgent.workflow.persistence import Persistence


def _fake_config(tmp_path):
    return SimpleNamespace(
        tools={},
        workflow={"paths": {"runs_dir": str(tmp_path)}},
    )


class _FakeSpecificityAdapter:
    """Mimics ``EnsembleAdapter.predict_specificity_batch`` by replaying
    pre-scripted rows back through the supplied callbacks."""

    def __init__(self, rows: list[dict], cancel_after: int | None = None) -> None:
        self._rows = rows
        self._cancel_after = cancel_after
        self.received_skip_pairs: list[tuple[int, str]] | None = None

    def predict_specificity_batch(
        self,
        *,
        candidates,
        targets,
        progress_callback,
        row_callback,
        cancel_event,
        timeout_seconds,
        progress_every,
        skip_pairs,
    ):
        self.received_skip_pairs = list(skip_pairs) if skip_pairs else None

        total = len(candidates) * len(targets)
        skipped = len(self.received_skip_pairs or [])
        done = 0
        for idx, row in enumerate(self._rows):
            row_callback(row)
            done += 1
            progress_callback(
                done,
                total - skipped,
                {"target_name": row.get("target_name", "")},
            )
            if self._cancel_after is not None and idx + 1 >= self._cancel_after:
                cancel_event.set()
                return {"cancelled": True, "total": total}
        return {"total": total}


def _make_state(persistence, *, run_id: str, candidate_ids: list[str]):
    state = persistence.init_run(run_id)
    state.current_step = Step.SPECIFICITY_FILTER
    state.target_molecule = TargetMolecule(
        input_text="caffeine",
        resolved_name="Caffeine",
        smiles="Cn1cnc2n(C)c(=O)n(C)c(=O)c12",
        resolution_status="resolved",
    )
    state.analogs = [
        TargetMolecule(
            input_text="theobromine",
            resolved_name="Theobromine",
            smiles="Cn1cnc2[nH]c(=O)n(C)c(=O)c12",
            resolution_status="resolved",
        ),
        TargetMolecule(
            input_text="paraxanthine",
            resolved_name="Paraxanthine",
            smiles="Cn1c(=O)[nH]c2ncn(C)c2c1=O",
            resolution_status="resolved",
        ),
    ]
    state.candidates = [
        CandidateSequence(sequence="ACGU", candidate_id=cid) for cid in candidate_ids
    ]
    persistence.save(state)
    return state


def test_specificity_runner_writes_artifact_and_summary(tmp_path, monkeypatch):
    persistence = Persistence(runs_dir=tmp_path)
    state = _make_state(persistence, run_id="spec_normal", candidate_ids=["c1", "c2"])

    rows = [
        # candidate c1
        {"target_idx": 0, "target_name": "Caffeine", "candidate_id": "c1", "label": 1, "probability": 0.9},
        {"target_idx": 1, "target_name": "Theobromine", "candidate_id": "c1", "label": 0, "probability": 0.1},
        {"target_idx": 2, "target_name": "Paraxanthine", "candidate_id": "c1", "label": 0, "probability": 0.2},
        # candidate c2 - fails on paraxanthine analog
        {"target_idx": 0, "target_name": "Caffeine", "candidate_id": "c2", "label": 1, "probability": 0.8},
        {"target_idx": 1, "target_name": "Theobromine", "candidate_id": "c2", "label": 0, "probability": 0.3},
        {"target_idx": 2, "target_name": "Paraxanthine", "candidate_id": "c2", "label": 1, "probability": 0.7},
    ]
    fake_adapter = _FakeSpecificityAdapter(rows)

    monkeypatch.setattr("aptgent.jobs.runner.load_config", lambda: _fake_config(tmp_path))
    monkeypatch.setattr(
        "aptgent.bootstrap.container.create_prediction_adapter",
        lambda _tools_config: fake_adapter,
    )

    events_path = persistence.job_events_file(state.run_id, "specificity_filter")
    writer = EventWriter(events_path)
    try:
        _run_specificity(writer, state, persistence)
    finally:
        writer.close()

    events = list(EventReader(events_path).iter_events())
    done = events[-1]

    assert done["type"] == "done"
    assert done["summary"]["kept"] == 1
    assert done["summary"]["removed"] == 1
    assert done["summary"]["candidates"] == 2

    hits = [e for e in events if e["type"] == "hit"]
    hit_by_cid = {h["candidate_id"]: h for h in hits}
    assert hit_by_cid["c1"]["extra"]["status"] == "kept"
    assert hit_by_cid["c2"]["extra"]["status"] == "removed"
    assert hit_by_cid["c2"]["extra"]["failed_analogs"] == ["Paraxanthine"]

    artifact = tmp_path / "spec_normal" / "artifacts" / "specificity_results.jsonl"
    assert artifact.exists()
    lines = [json.loads(ln) for ln in artifact.read_text().splitlines() if ln.strip()]
    assert lines[0]["meta"]["candidate_ids"] == ["c1", "c2"]
    written = {ln["candidate_id"]: ln for ln in lines[1:]}
    assert written["c1"]["status"] == "kept"
    assert written["c2"]["status"] == "removed"

    saved = persistence.load(state.run_id)
    assert saved is not None
    statuses = {r.candidate_id: r.status for r in saved.specificity_results}
    assert statuses == {"c1": "kept", "c2": "removed"}


def test_specificity_runner_resumes_from_existing_artifact(tmp_path, monkeypatch):
    persistence = Persistence(runs_dir=tmp_path)
    state = _make_state(persistence, run_id="spec_resume", candidate_ids=["c1", "c2"])

    artifact_dir = persistence.get_artifact_dir(state.run_id)
    artifact_path = artifact_dir / "specificity_results.jsonl"
    meta = {
        "candidate_ids": ["c1", "c2"],
        "target_names": ["Caffeine", "Theobromine", "Paraxanthine"],
        "target_smiles": [
            "Cn1cnc2n(C)c(=O)n(C)c(=O)c12",
            "Cn1cnc2[nH]c(=O)n(C)c(=O)c12",
            "Cn1c(=O)[nH]c2ncn(C)c2c1=O",
        ],
    }
    with open(artifact_path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"meta": meta}) + "\n")
        f.write(json.dumps({"candidate_id": "c1", "status": "kept", "failed_analogs": []}) + "\n")

    rows = [
        # only c2 remains
        {"target_idx": 0, "target_name": "Caffeine", "candidate_id": "c2", "label": 1, "probability": 0.8},
        {"target_idx": 1, "target_name": "Theobromine", "candidate_id": "c2", "label": 0, "probability": 0.3},
        {"target_idx": 2, "target_name": "Paraxanthine", "candidate_id": "c2", "label": 0, "probability": 0.2},
    ]
    fake_adapter = _FakeSpecificityAdapter(rows)

    monkeypatch.setattr("aptgent.jobs.runner.load_config", lambda: _fake_config(tmp_path))
    monkeypatch.setattr(
        "aptgent.bootstrap.container.create_prediction_adapter",
        lambda _tools_config: fake_adapter,
    )

    events_path = persistence.job_events_file(state.run_id, "specificity_filter")
    writer = EventWriter(events_path)
    try:
        _run_specificity(writer, state, persistence)
    finally:
        writer.close()

    assert fake_adapter.received_skip_pairs is not None
    skip_pairs = set(tuple(p) for p in fake_adapter.received_skip_pairs)
    assert (0, "c1") in skip_pairs
    assert (1, "c1") in skip_pairs
    assert (2, "c1") in skip_pairs
    # c2 must not be skipped
    assert (0, "c2") not in skip_pairs

    events = list(EventReader(events_path).iter_events())
    done = events[-1]
    assert done["type"] == "done"
    assert done["summary"]["kept"] == 2
    assert done["summary"]["removed"] == 0


def test_specificity_runner_handles_no_analogs(tmp_path, monkeypatch):
    persistence = Persistence(runs_dir=tmp_path)
    state = persistence.init_run("spec_no_analogs")
    state.current_step = Step.SPECIFICITY_FILTER
    state.target_molecule = TargetMolecule(
        input_text="caffeine",
        resolved_name="Caffeine",
        smiles="Cn1cnc2n(C)c(=O)n(C)c(=O)c12",
        resolution_status="resolved",
    )
    state.analogs = [
        TargetMolecule(input_text="unknown", resolution_status="failed"),
    ]
    state.candidates = [
        CandidateSequence(sequence="ACGU", candidate_id="c1"),
        CandidateSequence(sequence="ACGA", candidate_id="c2"),
    ]
    persistence.save(state)

    monkeypatch.setattr("aptgent.jobs.runner.load_config", lambda: _fake_config(tmp_path))
    called: dict[str, int] = {"adapter_count": 0}

    class _ShouldNotRun:
        def predict_specificity_batch(self, **_kwargs):
            called["adapter_count"] += 1
            raise AssertionError("adapter must not be invoked when no valid analogs")

    monkeypatch.setattr(
        "aptgent.bootstrap.container.create_prediction_adapter",
        lambda _tools_config: _ShouldNotRun(),
    )

    events_path = persistence.job_events_file(state.run_id, "specificity_filter")
    writer = EventWriter(events_path)
    try:
        _run_specificity(writer, state, persistence)
    finally:
        writer.close()

    assert called["adapter_count"] == 0
    saved = persistence.load(state.run_id)
    assert saved is not None
    statuses = {r.candidate_id: r.status for r in saved.specificity_results}
    assert statuses == {"c1": "kept", "c2": "kept"}

    events = list(EventReader(events_path).iter_events())
    done = events[-1]
    assert done["type"] == "done"
    assert done["summary"]["kept"] == 2
    assert done["summary"]["removed"] == 0
