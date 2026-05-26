from __future__ import annotations

import json
import threading
from unittest.mock import MagicMock, patch

from mutation_batch_protocol_helpers import LineReader


class _SpecPopen:
    """Stub Popen that replays a specificity-batch line-JSON stream."""

    def __init__(self, cmd, lines, **kwargs) -> None:
        self.stdout = LineReader()
        self.stderr = LineReader()
        self.stdin = MagicMock()
        self.returncode = 0
        self._cmd = cmd
        self._lines = lines

    def feed(self) -> None:
        for line in self._lines:
            self.stdout.put_line(line)
        self.stdout.close()
        self.stderr.close()

    def wait(self, timeout=None) -> int:
        return self.returncode


class _SpecPopenFactory:
    def __init__(self, lines) -> None:
        self._lines = lines
        self.proc: _SpecPopen | None = None
        self.cmd: list[str] | None = None

    def __call__(self, cmd, **kwargs):
        self.cmd = list(cmd)
        self.proc = _SpecPopen(cmd, self._lines, **kwargs)
        timer = threading.Timer(0.05, self.proc.feed)
        timer.daemon = True
        timer.start()
        return self.proc


def _candidates_targets():
    from aptgent.domain.models import CandidateSequence, TargetMolecule

    candidates = [
        CandidateSequence(sequence="ACGU", candidate_id="c1"),
        CandidateSequence(sequence="ACGA", candidate_id="c2"),
    ]
    targets = [
        TargetMolecule(input_text="caffeine", resolved_name="Caffeine", smiles="C1"),
        TargetMolecule(input_text="theobromine", resolved_name="Theobromine", smiles="C2"),
    ]
    return candidates, targets


def test_adapter_predict_specificity_batch_parses_protocol():
    from aptgent.adapters.predictor import EnsembleAdapter

    candidates, targets = _candidates_targets()
    lines = [
        json.dumps({"type": "ready", "device": "cpu", "model_order": ["a.pkl"], "total": 4}),
        json.dumps({"type": "progress", "done": 0, "total": 4, "target_idx": 0, "target_name": "Caffeine"}),
        json.dumps({"type": "row", "target_idx": 0, "target_name": "Caffeine", "candidate_id": "c1", "label": 1, "probability": 0.9}),
        json.dumps({"type": "progress", "done": 1, "total": 4, "target_idx": 0, "target_name": "Caffeine"}),
        json.dumps({"type": "row", "target_idx": 0, "target_name": "Caffeine", "candidate_id": "c2", "label": 1, "probability": 0.8}),
        json.dumps({"type": "progress", "done": 2, "total": 4, "target_idx": 0, "target_name": "Caffeine"}),
        json.dumps({"type": "progress", "done": 2, "total": 4, "target_idx": 1, "target_name": "Theobromine"}),
        json.dumps({"type": "row", "target_idx": 1, "target_name": "Theobromine", "candidate_id": "c1", "label": 0, "probability": 0.1}),
        json.dumps({"type": "progress", "done": 3, "total": 4, "target_idx": 1, "target_name": "Theobromine"}),
        json.dumps({"type": "row", "target_idx": 1, "target_name": "Theobromine", "candidate_id": "c2", "label": 1, "probability": 0.6}),
        json.dumps({"type": "progress", "done": 4, "total": 4, "target_idx": 1, "target_name": "Theobromine"}),
        json.dumps({"type": "done", "total": 4, "cancelled": False}),
    ]
    factory = _SpecPopenFactory(lines)

    rows: list[dict] = []
    progresses: list[tuple[int, int, dict]] = []

    adapter = EnsembleAdapter(model_dir="/fake/models")
    with patch("aptgent.adapters.predictor.subprocess.Popen", factory):
        summary = adapter.predict_specificity_batch(
            candidates=candidates,
            targets=targets,
            progress_callback=lambda d, t, info: progresses.append((d, t, info)),
            row_callback=lambda row: rows.append(row),
            cancel_event=None,
            timeout_seconds=None,
            progress_every=1,
        )

    assert summary["device"] == "cpu"
    assert summary["model_order"] == ["a.pkl"]
    assert summary["total"] == 4
    assert "cancelled" not in summary

    assert len(rows) == 4
    assert {r["candidate_id"] for r in rows} == {"c1", "c2"}
    assert rows[2]["target_name"] == "Theobromine"

    assert (4, 4, {"target_idx": 1, "target_name": "Theobromine"}) in progresses
    assert any(p[2].get("target_name") == "Caffeine" for p in progresses)

    assert factory.cmd is not None
    assert "specificity-batch" in factory.cmd
    assert "--candidates-json" in factory.cmd
    assert "--targets-json" in factory.cmd


def test_adapter_predict_specificity_batch_handles_cancel():
    from aptgent.adapters.predictor import EnsembleAdapter

    candidates, targets = _candidates_targets()
    lines = [
        json.dumps({"type": "ready", "device": "cpu", "model_order": [], "total": 4}),
        json.dumps({"type": "row", "target_idx": 0, "target_name": "Caffeine", "candidate_id": "c1", "label": 1, "probability": 0.9}),
        json.dumps({"type": "done", "total": 4, "cancelled": True}),
    ]
    factory = _SpecPopenFactory(lines)

    cancel_event = threading.Event()

    adapter = EnsembleAdapter(model_dir="/fake/models")
    with patch("aptgent.adapters.predictor.subprocess.Popen", factory):
        summary = adapter.predict_specificity_batch(
            candidates=candidates,
            targets=targets,
            cancel_event=cancel_event,
            timeout_seconds=None,
            progress_every=1,
        )

    assert summary.get("cancelled") is True
