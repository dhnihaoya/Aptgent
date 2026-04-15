from __future__ import annotations

import csv
import os
from typing import Any

try:
    from rdkit import Chem

    _RDKIT_AVAILABLE = True
except Exception:  # pragma: no cover
    _RDKIT_AVAILABLE = False

from aptgent.domain.models import CandidateSequence, SpatialRankResult, TargetMolecule

_DEFAULT_MATRIX_PATH = os.path.join(
    os.path.dirname(__file__), "..", "config", "spatial_interaction_matrix.csv"
)

# SMARTS patterns for the 24 functional groups in the matrix.
# Keys must match the column names in the CSV (after the first "base" column).
_GROUP_SMARTS: dict[str, str] = {
    "5-membered heterocyclic ring": "[$([n,o,s]1cccc1)]",
    "6-membered heterocyclic ring": "[$([n]1ccccc1)]",
    "Aliphatic carboxyl group": "[$([CX3](=O)[OX2H1]);!$([CX3](=O)[OX2H1]c)]",
    "Aliphatic hydroxyl group": "[OX2H;!$(Oc);!$(OC=O)]",
    "Aromatic carboxyl group": "cC(=O)[OX2H1]",
    "Aromatic nitrogen": "[n;H0,H1]",
    "Aromatic amino group": "c[NH2,NH;!$(NC=O)]",
    "Aromatic hydroxyl group": "c[OH1;!$(OC=O)]",
    "Carbonyl group": "[#6]=[OX1]",
    "Tertiary amine group": "[NX3;H0;!$(N=O);!$(NC=O)]",
    "Primary amino group": "[NX3;H2;!$(NC=O)]",
    "Secondary amino group": "[NX3;H1;!$(NC=O);!$(Nc)]",
    "Amide group": "C(=O)[NX3]",
    "Aniline group": "c1ccccc1[NH2]",
    "Benzene ring": "c1ccccc1",
    "Guanidine group": "NC(=N)N",
    "Imidazole ring": "c1c[nH]cn1",
    "Nitrile group": "C#N",
    "Oxazole ring": "c1ncoc1",
    "Oxime group": "C=N[OH1]",
    "Phosphoric acid group": "P(=O)([OX2H,OX1-])([OX2H,OX1-])[OX2H,OX1-]",
    "Methyl group": "[CH3]",
    "Thiazole ring": "c1ncsc1",
    "Thiophene ring": "c1ccsc1",
}


class SpatialRankAdapter:
    """Deterministic spatial ranker based on base–functional-group interaction matrix."""

    def __init__(self, matrix_path: str | None = None) -> None:
        self.matrix_path = matrix_path or _DEFAULT_MATRIX_PATH
        self._matrix: dict[str, dict[str, float]] = {}
        self._groups: list[str] = []
        self._load_matrix()
        self._smarts_patterns: dict[str, Any] = {}
        if _RDKIT_AVAILABLE:
            for name, smarts in _GROUP_SMARTS.items():
                try:
                    self._smarts_patterns[name] = Chem.MolFromSmarts(smarts)
                except Exception:
                    self._smarts_patterns[name] = None

    def _load_matrix(self) -> None:
        with open(self.matrix_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                raise ValueError(
                    f"Spatial interaction matrix CSV has no header row: {self.matrix_path}"
                )
            self._groups = [k for k in reader.fieldnames if k != "base"]
            for row in reader:
                base = row["base"].strip()
                self._matrix[base] = {g: float(row[g]) for g in self._groups}

    def _detect_groups(self, smiles: str) -> dict[str, int]:
        """Return counts of detected functional groups in the given SMILES."""
        counts: dict[str, int] = {}
        if not _RDKIT_AVAILABLE or not smiles:
            return counts
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return counts
        for name, pattern in self._smarts_patterns.items():
            if pattern is None:
                continue
            matches = mol.GetSubstructMatches(pattern)
            counts[name] = len(matches)
        return counts

    @staticmethod
    def _map_base(base: str) -> str | None:
        ub = base.upper()
        if ub == "A":
            return "A"
        if ub in ("T", "U"):
            return "T/U"
        if ub == "C":
            return "C"
        if ub == "G":
            return "G"
        return None

    def _score_sequence(self, sequence: str, present_groups: dict[str, int]) -> float:
        if not sequence or not present_groups:
            return 0.0
        total = 0.0
        for base in sequence:
            mapped = self._map_base(base)
            if mapped is None:
                continue
            row = self._matrix.get(mapped, {})
            for group, count in present_groups.items():
                total += row.get(group, 0.0) * count
        return total / len(sequence)

    def rank_batch(
        self,
        candidates: list[CandidateSequence],
        target: TargetMolecule,
    ) -> list[SpatialRankResult]:
        """Score candidates using the spatial interaction matrix."""
        group_counts = self._detect_groups(target.smiles or "")
        present_groups = {g: c for g, c in group_counts.items() if c > 0}

        results: list[SpatialRankResult] = []
        for cand in candidates:
            score = self._score_sequence(cand.sequence, present_groups)
            results.append(
                SpatialRankResult(
                    candidate_id=cand.candidate_id or "",
                    spatial_score=score,
                    detected_groups=list(present_groups.keys()),
                    rank=0,
                    raw_outputs={
                        "group_counts": group_counts,
                        "sequence_length": len(cand.sequence),
                    },
                )
            )

        # Assign ranks: higher score = better rank (1-based)
        sorted_results = sorted(
            results, key=lambda r: r.spatial_score, reverse=True
        )
        for i, res in enumerate(sorted_results):
            res.rank = i + 1

        # Return in original candidate order but with rank populated
        return results
