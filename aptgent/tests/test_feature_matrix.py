"""Tests for vectorized build_feature_matrix against per-sample build_feature_vector."""

from __future__ import annotations

import numpy as np
import pytest


def _skip_no_rdkit():
    try:
        from rdkit import Chem  # noqa: F401
    except ImportError:
        pytest.skip("rdkit not available")


def test_matrix_matches_vector_single_sequence():
    _skip_no_rdkit()
    from aptgent.predictor_runtime.features import (
        build_feature_matrix,
        build_feature_vector,
        molecular_descriptors,
    )

    seq = "ATGCATGC"
    smiles = "c1ccccc1"  # benzene
    k_list = [1, 2]

    desc = molecular_descriptors(smiles)
    single = build_feature_vector(seq, smiles, k_list)
    matrix = build_feature_matrix([seq], desc, k_list)

    assert matrix.shape == (1, len(single))
    np.testing.assert_allclose(matrix[0], single, atol=1e-12)


def test_matrix_matches_vector_multiple_sequences():
    _skip_no_rdkit()
    from aptgent.predictor_runtime.features import (
        build_feature_matrix,
        build_feature_vector,
        molecular_descriptors,
    )

    sequences = ["AATT", "ATGC", "GCGC"]
    smiles = "CCO"  # ethanol
    k_list = [1, 2]

    desc = molecular_descriptors(smiles)
    matrix = build_feature_matrix(sequences, desc, k_list)

    assert matrix.shape[0] == 3
    for i, seq in enumerate(sequences):
        single = build_feature_vector(seq, smiles, k_list)
        np.testing.assert_allclose(matrix[i], single, atol=1e-12)


def test_matrix_empty_sequences():
    _skip_no_rdkit()
    from aptgent.predictor_runtime.features import build_feature_matrix

    result = build_feature_matrix([], [1.0, 2.0], [1])
    assert result.shape == (0, 0)


def test_matrix_short_sequence_k_too_large():
    _skip_no_rdkit()
    from aptgent.predictor_runtime.features import (
        build_feature_matrix,
        build_feature_vector,
        molecular_descriptors,
    )

    # Sequence shorter than k: kmer features should be all zeros
    seq = "AT"
    smiles = "CCO"
    k_list = [4]

    desc = molecular_descriptors(smiles)
    single = build_feature_vector(seq, smiles, k_list)
    matrix = build_feature_matrix([seq], desc, k_list)

    np.testing.assert_allclose(matrix[0], single, atol=1e-12)


def test_matrix_accepts_encoded_array():
    _skip_no_rdkit()
    from aptgent.predictor_runtime.features import (
        _ENCODE_TABLE,
        build_feature_matrix,
        build_feature_vector,
        molecular_descriptors,
    )

    sequences = ["AATT", "GGCC"]
    smiles = "c1ccccc1"
    k_list = [1, 2]

    desc = molecular_descriptors(smiles)

    # Encode manually
    joined = "".join(sequences).encode("ascii")
    encoded = _ENCODE_TABLE[np.frombuffer(joined, dtype=np.uint8)].reshape(2, 4)

    matrix = build_feature_matrix(encoded, desc, k_list)

    for i, seq in enumerate(sequences):
        single = build_feature_vector(seq, smiles, k_list)
        np.testing.assert_allclose(matrix[i], single, atol=1e-12)


def test_nan_descriptors_replaced_with_zero():
    _skip_no_rdkit()
    from aptgent.predictor_runtime.features import (
        build_feature_matrix,
        molecular_descriptors,
    )

    # Invalid SMILES produces NaN descriptors
    desc = molecular_descriptors("invalid_smiles_xyz")
    matrix = build_feature_matrix(["ATGC"], desc, [1])

    assert not np.any(np.isnan(matrix))
