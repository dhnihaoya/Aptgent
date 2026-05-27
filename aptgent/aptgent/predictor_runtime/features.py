"""Feature extraction utilities for aptamer-small molecule prediction."""

from __future__ import annotations

from itertools import product
from functools import lru_cache

import numpy as np
from rdkit import Chem
from rdkit.Chem import Descriptors


def rna_to_dna(sequence: str) -> str:
    """Convert RNA sequence to DNA form by replacing U with T."""
    return sequence.replace("U", "T").replace("u", "t")


@lru_cache(maxsize=4)
def _get_all_kmers(k: int) -> tuple[str, ...]:
    """Return all possible k-mers in lexicographic order."""
    bases = ["A", "T", "G", "C"]
    return tuple("".join(part) for part in product(bases, repeat=k))


def kmer_frequency(sequence: str, k: int) -> list[float]:
    """Compute the normalized frequency vector for one k-mer size."""
    sequence = sequence.upper()
    all_kmers = _get_all_kmers(k)
    n_kmers = len(sequence) - k + 1
    if n_kmers <= 0:
        return [0.0] * len(all_kmers)

    counts = {kmer: 0 for kmer in all_kmers}
    for i in range(n_kmers):
        sub = sequence[i : i + k]
        if sub in counts:
            counts[sub] += 1

    return [counts[kmer] / n_kmers for kmer in all_kmers]


def kmer_features(sequence: str, k_list: list[int]) -> list[float]:
    """Concatenate k-mer frequency vectors for each requested k."""
    sequence = rna_to_dna(sequence)
    features: list[float] = []
    for k in k_list:
        features.extend(kmer_frequency(sequence, k))
    return features


_NEWLY_ADDED_DESCRIPTORS = frozenset(
    {
        "fr_term_acetylene",
        "fr_tetrazole",
        "fr_thiazole",
        "fr_thiocyan",
        "fr_thiophene",
        "fr_unbrch_alkane",
        "fr_urea",
    }
)

_DESCRIPTOR_FUNCS = [
    (name, func)
    for name, func in Descriptors.descList
    if name != "Ipc" and name not in _NEWLY_ADDED_DESCRIPTORS
]


def molecular_descriptors(smiles: str) -> list[float]:
    """Calculate the RDKit descriptor vector expected by the trained models."""
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return [float("nan")] * len(_DESCRIPTOR_FUNCS)

    values: list[float] = []
    for _name, func in _DESCRIPTOR_FUNCS:
        try:
            value = func(mol)
            if value is None:
                value = float("nan")
            values.append(float(value))
        except Exception:
            values.append(float("nan"))
    return values


MER_K_MAP = {
    "1mer": [1],
    "2mer": [2],
    "4mer": [4],
    "23mer": [2, 3],
    "24mer": [2, 4],
    "123mer": [1, 2, 3],
    "124mer": [1, 2, 4],
    "1234mer": [1, 2, 3, 4],
}


def build_feature_vector(sequence: str, smiles: str, k_list: list[int]) -> np.ndarray:
    """Build the complete model feature vector for one sequence-target pair."""
    kmer = kmer_features(sequence, k_list)
    descriptors = molecular_descriptors(smiles)
    vector = np.array(kmer + descriptors, dtype=np.float64)
    return np.nan_to_num(vector, nan=0.0)


# ---------------------------------------------------------------------------
# Vectorized batch feature matrix (for mutation enumeration)
# ---------------------------------------------------------------------------

_ENCODE_TABLE = np.zeros(256, dtype=np.int32)
_ENCODE_TABLE[ord("A")] = 0
_ENCODE_TABLE[ord("a")] = 0
_ENCODE_TABLE[ord("T")] = 1
_ENCODE_TABLE[ord("t")] = 1
_ENCODE_TABLE[ord("U")] = 1
_ENCODE_TABLE[ord("u")] = 1
_ENCODE_TABLE[ord("G")] = 2
_ENCODE_TABLE[ord("g")] = 2
_ENCODE_TABLE[ord("C")] = 3
_ENCODE_TABLE[ord("c")] = 3


def _encode_sequences(sequences: list[str]) -> np.ndarray:
    """Encode a list of same-length DNA sequences as an int array (A=0 T=1 G=2 C=3)."""
    if not sequences:
        return np.empty((0, 0), dtype=np.int32)
    joined = "".join(sequences).encode("ascii")
    encoded = _ENCODE_TABLE[np.frombuffer(joined, dtype=np.uint8)]
    return encoded.reshape(len(sequences), len(sequences[0]))


def build_feature_matrix(
    sequences: list[str] | np.ndarray,
    precomputed_desc: list[float],
    k_list: list[int],
) -> np.ndarray:
    """Vectorized batch feature matrix construction.

    All sequences **must** have the same length.  Molecular descriptors are
    tiled across the batch so RDKit is called only once.

    Returns ndarray of shape ``(n_sequences, total_feature_dim)`` with NaN→0.
    """
    if isinstance(sequences, np.ndarray):
        if sequences.size == 0:
            return np.empty((0, 0))
        if sequences.ndim != 2:
            raise ValueError("Encoded sequence array must be 2-D")

        if np.issubdtype(sequences.dtype, np.integer) and (
            sequences.size == 0
            or (int(np.min(sequences)) >= 0 and int(np.max(sequences)) <= 3)
        ):
            encoded = sequences.astype(np.int32, copy=False)
        else:
            encoded = _ENCODE_TABLE[sequences.astype(np.uint8, copy=False)]
    else:
        if not sequences:
            return np.empty((0, 0))
        encoded = _encode_sequences(sequences)

    N = encoded.shape[0]
    desc_arr = np.array(precomputed_desc, dtype=np.float64)
    L = encoded.shape[1]

    all_kmer = []
    for k in k_list:
        dim = 4 ** k
        n_kmers = L - k + 1
        if n_kmers <= 0:
            all_kmer.append(np.zeros((N, dim), dtype=np.float64))
            continue

        indices = np.zeros((N, n_kmers), dtype=np.int32)
        for i in range(k):
            indices = indices * 4 + encoded[:, i : i + n_kmers]

        offsets = np.arange(N, dtype=np.int32)[:, None] * dim
        flat = (indices + offsets).ravel()
        counts = np.bincount(flat, minlength=N * dim).reshape(N, dim).astype(np.float64)
        counts /= n_kmers
        all_kmer.append(counts)

    kmer_matrix = np.hstack(all_kmer)
    desc_matrix = np.tile(desc_arr, (N, 1))
    result = np.hstack([kmer_matrix, desc_matrix])
    return np.nan_to_num(result, nan=0.0)
