"""Tests for the mutation-batch subprocess protocol and adapter parsing.

Uses a stubbed Popen to avoid needing the real predictor environment.
"""

from __future__ import annotations

import json
import queue
import threading
from unittest.mock import MagicMock, patch

import pytest


class _LineReader:
    """File-like object backed by a queue, simulates pipe line-by-line reads."""

    def __init__(self):
        self._q = queue.Queue()
        self._closed = False

    def put_line(self, line: str) -> None:
        self._q.put(line)

    def close(self) -> None:
        self._q.put(None)  # sentinel

    def __iter__(self):
        return self

    def __next__(self):
        item = self._q.get()
        if item is None:
            raise StopIteration
        return item

    def read(self) -> str:
        """Read all remaining content (simulates stderr.read())."""
        lines = []
        while True:
            item = self._q.get()
            if item is None:
                break
            lines.append(item)
        return "".join(lines)
class _FakePopen:
    """Stub subprocess.Popen that simulates the mutation-batch line-JSON protocol."""

    def __init__(self, cmd, **kwargs):
        self.stdout = _LineReader()
        self.stderr = _LineReader()
        self.stdin = MagicMock()
        self.returncode = 0
        self._cmd = cmd
        self._lines = [
            json.dumps({"type": "ready", "model_order": ["m1.pkl", "m2.pkl"], "device": "cpu"}),
            json.dumps({"type": "progress", "done": 100, "total": 256}),
            json.dumps({
                "type": "hit",
                "sequence": "ATGCTAGC",
                "mean_probability": 0.95,
                "model_probabilities": [0.92, 0.98],
            }),
            json.dumps({"type": "progress", "done": 256, "total": 256}),
            json.dumps({"type": "done", "total": 256, "hits": 1}),
        ]

    def feed_lines(self):
        for line in self._lines:
            self.stdout.put_line(line)
        self.stdout.close()
        self.stderr.close()

    def wait(self, timeout=None):
        return self.returncode
class _FakePopenFactory:
    def __init__(self, popen_class=None):
        self._popen_class = popen_class or _FakePopen
        self.proc = None

    def __call__(self, cmd, **kwargs):
        self.proc = self._popen_class(cmd, **kwargs)
        timer = threading.Timer(0.05, self.proc.feed_lines)
        timer.daemon = True
        timer.start()
        return self.proc
def test_adapter_predict_mutation_batch_parses_protocol():
    from aptgent.adapters.predictor import EnsembleAdapter
    from aptgent.domain.models import TargetMolecule

    factory = _FakePopenFactory()

    progress_calls = []
    result_calls = []

    def on_progress(done, total, info):
        progress_calls.append((done, total))

    def on_result(result):
        result_calls.append(result)

    adapter = EnsembleAdapter(model_dir="/fake/models")

    with patch("aptgent.adapters.predictor.subprocess.Popen", factory):
        summary = adapter.predict_mutation_batch(
            base_sequence="ATGCGATC",
            target=TargetMolecule(input_text="test", smiles="c1ccccc1"),
            sites=[1, 3, 5],
            progress_callback=on_progress,
            result_callback=on_result,
            batch_size=100,
        )

    assert len(progress_calls) == 2
    assert progress_calls[0] == (100, 256)
    assert progress_calls[1] == (256, 256)

    assert len(result_calls) == 1
    hit = result_calls[0]
    assert hit["sequence"] == "ATGCTAGC"
    assert hit["ensemble_label"] == 1
    assert abs(hit["probability"] - 0.95) < 1e-6

    assert summary["total"] == 256
    assert summary["hits"] == 1
    assert summary["device"] == "cpu"
    assert len(summary["model_order"]) == 2
def test_adapter_mutation_batch_cancel():
    from aptgent.adapters.predictor import EnsembleAdapter
    from aptgent.domain.models import TargetMolecule

    class _HangingPopen(_FakePopen):
        """Popen stub that stays alive until a cancel is written on stdin."""

        def __init__(self, cmd, **kwargs):
            super().__init__(cmd, **kwargs)
            self._cancel_received = threading.Event()
            self.stdin = MagicMock()
            self.stdin.write = MagicMock(side_effect=self._on_write)
            self.stdin.flush = MagicMock()
            self.stdin.closed = False

        def _on_write(self, data):
            if "cancel" in data:
                self._cancel_received.set()

        def feed_lines(self):
            self.stdout.put_line(
                json.dumps({"type": "ready", "model_order": ["m1.pkl"], "device": "cpu"})
            )
            self._cancel_received.wait(timeout=5.0)
            self.stdout.put_line(json.dumps({"type": "done", "total": 0, "hits": 0, "cancelled": True}))
            self.stdout.close()
            self.stderr.close()

    factory = _FakePopenFactory(_HangingPopen)
    cancel_event = threading.Event()

    adapter = EnsembleAdapter(model_dir="/fake/models")

    def _cancel_soon():
        import time
        time.sleep(0.1)
        cancel_event.set()

    threading.Thread(target=_cancel_soon, daemon=True).start()

    with patch("aptgent.adapters.predictor.subprocess.Popen", factory):
        summary = adapter.predict_mutation_batch(
            base_sequence="ATGC",
            target=TargetMolecule(input_text="t", smiles="CCO"),
            sites=[0],
            cancel_event=cancel_event,
        )

    factory.proc.stdin.write.assert_called()
    assert summary.get("cancelled") is True
def test_adapter_mutation_batch_error():
    from aptgent.adapters.predictor import EnsembleAdapter
    from aptgent.domain.models import TargetMolecule

    class _ErrorPopen(_FakePopen):
        def __init__(self, cmd, **kwargs):
            super().__init__(cmd, **kwargs)
            self.returncode = 2
            self._lines = [
                json.dumps({"type": "ready", "model_order": [], "device": "cpu"}),
                json.dumps({"type": "error", "message": "Something went wrong"}),
            ]

        def feed_lines(self):
            super().feed_lines()
            self.stderr.put_line("Something went wrong")
            self.stderr.close()

    factory = _FakePopenFactory(_ErrorPopen)

    adapter = EnsembleAdapter(model_dir="/fake/models")

    with patch("aptgent.adapters.predictor.subprocess.Popen", factory):
        # The adapter now surfaces the JSON {"type": "error"} payload directly, which
        # is strictly more informative than the numeric exit code that preceded it.
        with pytest.raises(RuntimeError, match="Something went wrong"):
            adapter.predict_mutation_batch(
                base_sequence="ATGC",
                target=TargetMolecule(input_text="t", smiles="CCO"),
                sites=[0],
            )
