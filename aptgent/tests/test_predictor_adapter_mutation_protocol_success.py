from __future__ import annotations

from unittest.mock import patch

from mutation_batch_protocol_helpers import FakePopenFactory


def test_adapter_predict_mutation_batch_parses_protocol():
    from aptgent.adapters.predictor import EnsembleAdapter
    from aptgent.domain.models import TargetMolecule

    factory = FakePopenFactory()

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

    assert progress_calls == [(100, 256), (256, 256)]

    assert len(result_calls) == 1
    hit = result_calls[0]
    assert hit["sequence"] == "ATGCTAGC"
    assert hit["ensemble_label"] == 1
    assert abs(hit["probability"] - 0.95) < 1e-6
    assert hit["model_probabilities"] == [0.92, 0.98]
    assert hit["rank_probabilities"] == [0.9200000001, 0.9800000001]

    assert summary["total"] == 256
    assert summary["hits"] == 1
    assert summary["device"] == "cpu"
    assert len(summary["model_order"]) == 2
