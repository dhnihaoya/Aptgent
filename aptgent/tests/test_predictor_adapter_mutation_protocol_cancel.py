from __future__ import annotations

import json
import threading
import time
from unittest.mock import MagicMock, patch

from mutation_batch_protocol_helpers import FakePopen, FakePopenFactory


def test_adapter_mutation_batch_cancel():
    from aptgent.adapters.predictor import EnsembleAdapter
    from aptgent.domain.models import TargetMolecule

    class HangingPopen(FakePopen):
        """Popen stub that stays alive until a cancel is written on stdin."""

        def __init__(self, cmd, **kwargs) -> None:
            super().__init__(cmd, **kwargs)
            self._cancel_received = threading.Event()
            self.stdin = MagicMock()
            self.stdin.write = MagicMock(side_effect=self._on_write)
            self.stdin.flush = MagicMock()
            self.stdin.closed = False

        def _on_write(self, data):
            if "cancel" in data:
                self._cancel_received.set()

        def feed_lines(self) -> None:
            self.stdout.put_line(
                json.dumps(
                    {"type": "ready", "model_order": ["m1.pkl"], "device": "cpu"}
                )
            )
            self._cancel_received.wait(timeout=5.0)
            self.stdout.put_line(
                json.dumps({"type": "done", "total": 0, "hits": 0, "cancelled": True})
            )
            self.stdout.close()
            self.stderr.close()

    factory = FakePopenFactory(HangingPopen)
    cancel_event = threading.Event()

    adapter = EnsembleAdapter(model_dir="/fake/models")

    def cancel_soon() -> None:
        time.sleep(0.1)
        cancel_event.set()

    threading.Thread(target=cancel_soon, daemon=True).start()

    with patch("aptgent.adapters.predictor.subprocess.Popen", factory):
        summary = adapter.predict_mutation_batch(
            base_sequence="ATGC",
            target=TargetMolecule(input_text="t", smiles="CCO"),
            sites=[0],
            cancel_event=cancel_event,
        )

    factory.proc.stdin.write.assert_called()
    assert summary.get("cancelled") is True
