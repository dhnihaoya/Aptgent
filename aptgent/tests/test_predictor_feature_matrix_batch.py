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


def test_build_feature_matrix_ambiguous_bases_match_single(monkeypatch):
    """Batch path must agree with single-sample path for sequences with non-ATGC chars."""
    monkeypatch.setattr(
        runtime_features,
        "molecular_descriptors",
        lambda _smiles: [0.1, 0.2, 0.3],
    )

    sequences = ["AANTGC", "ATGNCC", "NAAACC"]
    matrix = runtime_features.build_feature_matrix(sequences, [0.1, 0.2, 0.3], [1, 2])
    expected = runtime_features.np.vstack(
        [
            runtime_features.build_feature_vector(seq, "ignored", [1, 2])
            for seq in sequences
        ]
    )

    assert matrix.shape == expected.shape
    assert runtime_features.np.allclose(matrix, expected), (
        f"Batch/single mismatch:\n{matrix}\nvs\n{expected}"
    )
