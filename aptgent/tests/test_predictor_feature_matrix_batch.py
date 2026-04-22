from __future__ import annotations

from aptgent.predictor_runtime import features as runtime_features


def test_build_feature_matrix_matches_single_vector_builder(monkeypatch):
    monkeypatch.setattr(
        runtime_features,
        "molecular_descriptors",
        lambda _smiles: [0.25, 0.75],
    )

    sequences = ["AA", "AG", "AT"]
    matrix = runtime_features.build_feature_matrix(sequences, [0.25, 0.75], [1, 2])
    expected = runtime_features.np.vstack(
        [
            runtime_features.build_feature_vector(sequence, "ignored", [1, 2])
            for sequence in sequences
        ]
    )

    assert matrix.shape == expected.shape
    assert runtime_features.np.allclose(matrix, expected)
