from __future__ import annotations

import csv
import math
import os
from typing import Any

try:
    from rdkit import Chem

    _RDKIT_AVAILABLE = True
except Exception:  # pragma: no cover
    _RDKIT_AVAILABLE = False

from aptgent.domain.models import (
    CandidateSequence,
    DockingResult,
    SpatialRankResult,
    TargetMolecule,
)
from aptgent.domain.ranking import competition_ranks, dense_ranks
from aptgent.domain.sequence import NUCLEOTIDE_TO_BASE

# Default contact cutoff in Angstroms. Paper Table 3 reports interaction
# distances in the 2.0-3.96 A range; 4.0 A is the conservative gate.
_DEFAULT_CONTACT_CUTOFF = 4.0

# PDB/PDBQT residue name -> matrix base type mapping.
# For spatial ranking, T and U are equivalent (both map to "T/U").
_RESIDUE_BASE_MAP: dict[str, str] = {
    k: ("T/U" if v in ("T", "U") else v)
    for k, v in NUCLEOTIDE_TO_BASE.items()
}

_DEFAULT_MATRIX_PATH = os.path.join(
    os.path.dirname(__file__), "..", "config", "spatial_interaction_matrix.csv"
)

# Phosphate atom names in nucleotide residues (PDB + legacy variants). The
# paper's interaction matrix is defined between aptamer *bases* and
# small-molecule functional groups, so contacts to the sugar ring or phosphate
# backbone must not be counted as base–group matches.
_PHOSPHATE_ATOM_NAMES = frozenset(
    {"P", "OP1", "OP2", "OP3", "O1P", "O2P", "O3P"}
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

    # ------------------------------------------------------------------
    # Pose-based rule matching (paper Section 3.4.3)
    # ------------------------------------------------------------------

    def _preferred_bases(self) -> dict[str, str]:
        """For each group, return the base with the highest interaction probability."""
        result: dict[str, str] = {}
        if not self._matrix:
            return result
        for group in self._groups:
            best_base = max(
                self._matrix, key=lambda b: self._matrix[b].get(group, 0.0)
            )
            result[group] = best_base
        return result

    def _detect_group_matches(self, smiles: str) -> dict[str, list[tuple[int, ...]]]:
        """Return per-group substructure matches (RDKit atom-index tuples)."""
        matches: dict[str, list[tuple[int, ...]]] = {}
        if not _RDKIT_AVAILABLE or not smiles:
            return matches
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return matches
        for name, pattern in self._smarts_patterns.items():
            if pattern is None:
                continue
            hits = mol.GetSubstructMatches(pattern)
            if hits:
                matches[name] = [tuple(h) for h in hits]
        return matches

    @staticmethod
    def _is_nucleobase_atom(atom_name: str) -> bool:
        """True if the atom belongs to the nucleobase, not the sugar/phosphate.

        Sugar-ring atoms carry a prime in PDB nomenclature (C1'..C5',
        O2'..O5'); some legacy PDBQT files write the prime as ``*``. Phosphate
        atoms use the fixed names in ``_PHOSPHATE_ATOM_NAMES``. Everything else
        on a nucleotide residue is treated as a base atom.
        """
        name = atom_name.strip().upper()
        if not name:
            return False
        if "'" in name or "*" in name:
            return False
        return name not in _PHOSPHATE_ATOM_NAMES

    @staticmethod
    def _parse_pdbqt_atoms(line: str) -> tuple[str, float, float, float] | None:
        """Parse an ATOM/HETATM line into (atom_name, x, y, z)."""
        if not (line.startswith("ATOM") or line.startswith("HETATM")):
            return None
        try:
            atom_name = line[12:16].strip()
            x = float(line[30:38])
            y = float(line[38:46])
            z = float(line[46:54])
        except (ValueError, IndexError):
            return None
        return (atom_name, x, y, z)

    def _parse_receptor_bases(
        self, pdbqt_path: str
    ) -> list[tuple[str, str, list[tuple[str, float, float, float]]]]:
        """Parse a receptor PDBQT into ``(base_type, residue_label, atoms)``.

        Residues whose name does not map to a nucleotide base are skipped.
        """
        residues: dict[str, list[tuple[str, float, float, float]]] = {}
        order: list[str] = []
        base_types: dict[str, str] = {}
        try:
            with open(pdbqt_path, "r", encoding="utf-8") as handle:
                for line in handle:
                    if not (line.startswith("ATOM") or line.startswith("HETATM")):
                        continue
                    atom = self._parse_pdbqt_atoms(line)
                    if atom is None:
                        continue
                    res_name = line[17:20].strip().upper()
                    base_type = _RESIDUE_BASE_MAP.get(res_name)
                    if base_type is None:
                        continue
                    # Keep only nucleobase atoms; sugar/phosphate backbone
                    # contacts are not base–group interactions (paper Sec. 3.4).
                    if not self._is_nucleobase_atom(atom[0]):
                        continue
                    chain = line[21:22].strip() or "_"
                    res_seq = line[22:26].strip()
                    label = f"{chain}:{res_name}:{res_seq}"
                    if label not in residues:
                        residues[label] = []
                        order.append(label)
                        base_types[label] = base_type
                    residues[label].append(atom)
        except OSError:
            return []
        return [(base_types[label], label, residues[label]) for label in order]

    def _parse_first_pose_atoms(
        self, output_pdbqt_path: str
    ) -> list[tuple[str, float, float, float]]:
        """Return the atoms of the first MODEL in a Vina output PDBQT."""
        atoms: list[tuple[str, float, float, float]] = []
        try:
            with open(output_pdbqt_path, "r", encoding="utf-8") as handle:
                for line in handle:
                    if line.startswith("ENDMDL"):
                        break
                    atom = self._parse_pdbqt_atoms(line)
                    if atom is not None:
                        atoms.append(atom)
        except OSError:
            return []
        return atoms

    @staticmethod
    def _is_hydrogen(atom_name: str) -> bool:
        """Heuristic: PDBQT hydrogen atom names start with 'H' (e.g. H, HD)."""
        name = atom_name.strip()
        return bool(name) and name[0] in ("H", "h")

    @staticmethod
    def _heavy_pose_atoms(
        pose_atoms: list[tuple[str, float, float, float]],
    ) -> list[tuple[str, float, float, float]]:
        return [a for a in pose_atoms if not SpatialRankAdapter._is_hydrogen(a[0])]

    @staticmethod
    def _rdkit_heavy_atom_count(smiles: str | None) -> int | None:
        """Heavy-atom count of the target as RDKit indexes it (no explicit H)."""
        if not _RDKIT_AVAILABLE or not smiles:
            return None
        mol = Chem.MolFromSmiles(smiles)
        return mol.GetNumAtoms() if mol is not None else None

    def _map_ligand_atoms_to_groups(
        self,
        group_matches: dict[str, list[tuple[int, ...]]],
        pose_atoms: list[tuple[str, float, float, float]],
    ) -> dict[str, list[list[tuple[str, float, float, float]]]]:
        """Map functional-group atom indices to docked pose coordinates.

        The "ligand" of the docked pose is the *target small molecule* (the
        same molecule for every candidate). ``group_matches`` holds RDKit
        heavy-atom indices from SMARTS hits on the target SMILES; we map them
        onto the pose's heavy atoms.

        NOTE: this assumes meeko preserved the RDKit heavy-atom ordering when
        writing the ligand PDBQT. That assumption can break if the meeko
        torsion-tree traversal reorders atoms; callers should consult the
        ``atom_map_reliable`` flag (see ``_rank_pose``) which compares the
        heavy-atom counts as a sanity check. Hydrogens are dropped first so
        polar-H rows do not shift the index alignment. Out-of-range indices
        are dropped.
        """
        heavy = self._heavy_pose_atoms(pose_atoms)
        result: dict[str, list[list[tuple[str, float, float, float]]]] = {}
        n = len(heavy)
        for group, occurrences in group_matches.items():
            group_occurrences: list[list[tuple[str, float, float, float]]] = []
            for occ in occurrences:
                coords = [heavy[i] for i in occ if 0 <= i < n]
                if coords:
                    group_occurrences.append(coords)
            if group_occurrences:
                result[group] = group_occurrences
        return result

    def _count_rule_matches(
        self,
        receptor_bases: list[tuple[str, str, list[tuple[str, float, float, float]]]],
        ligand_group_atoms: dict[str, list[list[tuple[str, float, float, float]]]],
        preferred_bases: dict[str, str],
        cutoff: float = _DEFAULT_CONTACT_CUTOFF,
    ) -> tuple[int, list[dict[str, Any]]]:
        """Count matched base–group interactions.

        Each *distinct* ``(group occurrence, preferred-base residue)`` contact
        within ``cutoff`` is counted once. A single functional-group occurrence
        sitting against several preferred-base residues therefore contributes
        one match per residue, matching the paper's list of matched base sites
        (Table 2) rather than collapsing to only the nearest residue.
        """
        count = 0
        details: list[dict[str, Any]] = []
        for group, occurrences in ligand_group_atoms.items():
            preferred = preferred_bases.get(group)
            if preferred is None:
                continue
            for occ_atoms in occurrences:
                for base_type, label, base_atoms in receptor_bases:
                    if base_type != preferred:
                        continue
                    min_dist: float | None = None
                    for _ln, lx, ly, lz in occ_atoms:
                        for _rn, rx, ry, rz in base_atoms:
                            dist = math.sqrt(
                                (lx - rx) ** 2 + (ly - ry) ** 2 + (lz - rz) ** 2
                            )
                            if min_dist is None or dist < min_dist:
                                min_dist = dist
                    if min_dist is not None and min_dist <= cutoff:
                        count += 1
                        details.append(
                            {
                                "group": group,
                                "preferred_base": preferred,
                                "base_residue": label,
                                "distance": round(min_dist, 3),
                            }
                        )
        return count, details

    @staticmethod
    def _competition_ranks(values: list[float], reverse: bool) -> list[int]:
        return competition_ranks(values, reverse=reverse)

    @staticmethod
    def _dense_ranks(values: list[float], reverse: bool) -> list[int]:
        return dense_ranks(values, reverse=reverse)

    def _can_use_pose_mode(self, docking_results: list[DockingResult]) -> bool:
        if not _RDKIT_AVAILABLE or not docking_results:
            return False
        for dr in docking_results:
            raw = dr.raw_outputs or {}
            out_pdbqt = raw.get("output_pdbqt")
            rec_pdbqt = raw.get("receptor_pdbqt")
            if (
                out_pdbqt
                and rec_pdbqt
                and os.path.isfile(out_pdbqt)
                and os.path.isfile(rec_pdbqt)
            ):
                return True
        return False

    def _rank_sequence(
        self,
        candidates: list[CandidateSequence],
        target: TargetMolecule,
    ) -> list[SpatialRankResult]:
        """Sequence-composition fallback ranking (no 3D pose available)."""
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
                        "mode": "sequence_fallback",
                        "group_counts": group_counts,
                        "sequence_length": len(cand.sequence),
                    },
                )
            )

        sorted_results = sorted(results, key=lambda r: r.spatial_score, reverse=True)
        for i, res in enumerate(sorted_results):
            res.rank = i + 1
        return results

    def _rank_pose(
        self,
        candidates: list[CandidateSequence],
        target: TargetMolecule,
        docking_results: list[DockingResult],
        cutoff: float = _DEFAULT_CONTACT_CUTOFF,
    ) -> list[SpatialRankResult]:
        """Pose-based binary rule-match ranking joined with docking affinity."""
        # The docked "ligand" is the target small molecule, so functional-group
        # detection runs once on the target SMILES and is shared by all
        # candidates (only the receptor/pose differ per candidate).
        group_matches = self._detect_group_matches(target.smiles or "")
        present_groups = list(group_matches.keys())
        preferred_bases = self._preferred_bases()
        expected_heavy = self._rdkit_heavy_atom_count(target.smiles)
        docking_by_id = {dr.candidate_id: dr for dr in docking_results}

        interaction_counts: list[int] = []
        docking_scores: list[float | None] = []
        contact_details: list[list[dict[str, Any]]] = []
        had_pose_flags: list[bool] = []
        atom_map_reliable_flags: list[bool | None] = []

        for cand in candidates:
            cand_id = cand.candidate_id or ""
            dr = docking_by_id.get(cand_id)
            raw = (dr.raw_outputs or {}) if dr else {}
            out_pdbqt = raw.get("output_pdbqt")
            rec_pdbqt = raw.get("receptor_pdbqt")

            count = 0
            details: list[dict[str, Any]] = []
            had_pose = bool(
                group_matches
                and out_pdbqt
                and rec_pdbqt
                and os.path.isfile(out_pdbqt)
                and os.path.isfile(rec_pdbqt)
            )
            atom_map_reliable: bool | None = None
            if had_pose:
                receptor_bases = self._parse_receptor_bases(rec_pdbqt)
                pose_atoms = self._parse_first_pose_atoms(out_pdbqt)
                heavy_pose = self._heavy_pose_atoms(pose_atoms)
                # Sanity check: index-based mapping is only trustworthy when the
                # pose heavy-atom count matches what RDKit produced for the
                # target. A mismatch flags likely meeko atom reordering.
                atom_map_reliable = (
                    None
                    if expected_heavy is None
                    else (expected_heavy == len(heavy_pose))
                )
                ligand_group_atoms = self._map_ligand_atoms_to_groups(
                    group_matches, pose_atoms
                )
                count, details = self._count_rule_matches(
                    receptor_bases, ligand_group_atoms, preferred_bases, cutoff
                )

            interaction_counts.append(count)
            docking_scores.append(dr.docking_score if dr else None)
            contact_details.append(details)
            had_pose_flags.append(had_pose)
            atom_map_reliable_flags.append(atom_map_reliable)

        # interaction_rank: competition ranking, higher count = better.
        interaction_ranks = self._competition_ranks(
            [float(c) for c in interaction_counts], reverse=True
        )
        # docking_rank: dense ranking, more negative score = better.
        # Missing scores sort last (worst) via +inf sentinel.
        score_keys = [
            s if s is not None else math.inf for s in docking_scores
        ]
        docking_ranks = self._dense_ranks(score_keys, reverse=False)

        results: list[SpatialRankResult] = []
        for idx, cand in enumerate(candidates):
            rank_sum = interaction_ranks[idx] + docking_ranks[idx]
            raw_outputs: dict[str, Any] = {
                # Candidates without usable pose files participate in the joint
                # ranking with count=0/score=None but are marked "no_pose" so the
                # absence of 3D evidence is not mistaken for a real zero-contact
                # pose result.
                "mode": "pose_rule_match" if had_pose_flags[idx] else "no_pose",
                "interaction_count": interaction_counts[idx],
                "interaction_rank": interaction_ranks[idx],
                "docking_score": docking_scores[idx],
                "docking_rank": docking_ranks[idx],
                "rank_sum": rank_sum,
                "contact_details": contact_details[idx],
            }
            if atom_map_reliable_flags[idx] is not None:
                raw_outputs["atom_map_reliable"] = atom_map_reliable_flags[idx]
            results.append(
                SpatialRankResult(
                    candidate_id=cand.candidate_id or "",
                    spatial_score=float(interaction_counts[idx]),
                    detected_groups=list(present_groups),
                    rank=0,
                    raw_outputs=raw_outputs,
                )
            )

        # Final ordinal rank: ascending rank_sum, then more-negative docking
        # score; remaining ties preserve input order (stable sort).
        order = sorted(
            range(len(results)),
            key=lambda i: (
                results[i].raw_outputs["rank_sum"],
                score_keys[i],
            ),
        )
        for ordinal, idx in enumerate(order, start=1):
            results[idx].rank = ordinal
        return results

    def rank_batch(
        self,
        candidates: list[CandidateSequence],
        target: TargetMolecule,
        docking_results: list[DockingResult] | None = None,
    ) -> list[SpatialRankResult]:
        """Rank candidates by spatial interaction.

        When docking poses are available, uses the pose-based binary
        rule-match scheme joined with docking affinity. Otherwise falls back
        to sequence-composition scoring.
        """
        if docking_results and self._can_use_pose_mode(docking_results):
            return self._rank_pose(candidates, target, docking_results)
        return self._rank_sequence(candidates, target)
