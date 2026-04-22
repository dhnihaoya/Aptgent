from __future__ import annotations

import pytest

from aptgent.predictor_runtime import features as runtime_features
from aptgent.predictor_runtime.predictor import EnsemblePredictor


class ThresholdModel:
    def __init__(self, feature_index: int, threshold: float, hit_probability: float) -> None:
        self.feature_index = feature_index
        self.threshold = threshold
        self.hit_probability = hit_probability

    def predict(self, X):
        return (X[:, self.feature_index] >= self.threshold).astype(int)

    def predict_proba(self, X):
        preds = self.predict(X)
        probs = [
            self.hit_probability if pred else 1.0 - self.hit_probability
            for pred in preds
        ]
        return runtime_features.np.column_stack([1.0 - runtime_features.np.array(probs), probs])
def test_predict_mutation_batch_filters_to_strict_ensemble_hits(monkeypatch):
    monkeypatch.setattr(
        runtime_features,
        "molecular_descriptors",
        lambda _smiles: [0.1],
    )

    predictor = object.__new__(EnsemblePredictor)
    predictor.models = [
        (ThresholdModel(feature_index=0, threshold=0.5, hit_probability=0.8), "1mer", "model_a"),
        (ThresholdModel(feature_index=2, threshold=0.5, hit_probability=0.9), "1mer", "model_b"),
    ]

    results = predictor.predict_mutation_batch("AA", "C1=CC=CC=C1", [1], batch_size=4)

    assert [item["sequence"] for item in results] == ["AG"]
    assert results[0]["ensemble_label"] == 1
    assert results[0]["mean_probability"] == pytest.approx(0.85)
