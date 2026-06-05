"""Canonical sequence conversion and residue mapping utilities."""
from __future__ import annotations


# ---------------------------------------------------------------------------
# RNA <-> DNA conversion
# ---------------------------------------------------------------------------

def dna_to_rna(sequence: str) -> str:
    """Convert DNA letters to RNA (T -> U). Preserves case and other chars."""
    return sequence.replace("T", "U").replace("t", "u")


def rna_to_dna(sequence: str) -> str:
    """Convert RNA letters to DNA (U -> T). Preserves case and other chars."""
    return sequence.replace("U", "T").replace("u", "t")


# ---------------------------------------------------------------------------
# Nucleotide code -> base mapping
# ---------------------------------------------------------------------------

# Maps PDB/PDBQT residue names to their standard base letter.
NUCLEOTIDE_TO_BASE: dict[str, str] = {
    "A": "A",
    "C": "C",
    "G": "G",
    "U": "U",
    "T": "T",
    "DA": "A",
    "DC": "C",
    "DG": "G",
    "DT": "T",
    "DU": "U",
    "RA": "A",
    "RC": "C",
    "RG": "G",
    "RU": "U",
    "ADE": "A",
    "CYT": "C",
    "GUA": "G",
    "URI": "U",
    "URA": "U",
    "THY": "T",
    "PSU": "U",
    "H2U": "U",
    "5MU": "U",
    "OMG": "G",
    "7MG": "G",
    "1MA": "A",
    "M2G": "G",
}
