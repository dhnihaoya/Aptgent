"""Feature extraction utilities for aptamer-small molecule prediction."""

from __future__ import annotations

from itertools import product

import numpy as np
from rdkit import Chem
from rdkit.Chem import Descriptors


def rna_to_dna(sequence: str) -> str:
    """Convert RNA sequence to DNA form by replacing U with T."""
    return sequence.replace("U", "T").replace("u", "t")


def _get_all_kmers(k: int) -> list[str]:
    """Return all possible k-mers in lexicographic order."""
    bases = ["A", "T", "G", "C"]
    return ["".join(part) for part in product(bases, repeat=k)]


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
