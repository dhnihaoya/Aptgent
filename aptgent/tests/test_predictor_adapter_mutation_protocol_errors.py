from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from mutation_batch_protocol_helpers import FakePopen, FakePopenFactory


def test_adapter_mutation_batch_error():
    from aptgent.adapters.predictor import EnsembleAdapter
    from aptgent.domain.models import TargetMolecule

    class ErrorPopen(FakePopen):
        def __init__(self, cmd, **kwargs) -> None:
            super().__init__(cmd, **kwargs)
            self.returncode = 2
            self._lines = [
                json.dumps({"type": "ready", "model_order": [], "device": "cpu"}),
                json.dumps({"type": "error", "message": "Something went wrong"}),
            ]

        def feed_lines(self) -> None:
            super().feed_lines()
            self.stderr.put_line("Something went wrong")
            self.stderr.close()

    factory = FakePopenFactory(ErrorPopen)
    adapter = EnsembleAdapter(model_dir="/fake/models")

    with patch("aptgent.adapters.predictor.subprocess.Popen", factory):
        with pytest.raises(RuntimeError, match="Something went wrong"):
            adapter.predict_mutation_batch(
                base_sequence="ATGC",
                target=TargetMolecule(input_text="t", smiles="CCO"),
                sites=[0],
            )
