from __future__ import annotations

import math
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from functools import lru_cache
from pathlib import Path

from aptgent.domain.models import (
    PdbAnalysisResult,
    PdbChainCandidate,
    PdbLigandCandidate,
    SecondaryStructure,
)

_PDB_ID = re.compile(r"\b([0-9][A-Za-z0-9]{3})\b")
_NUCLEOTIDE_CODES = {
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
    "ADE": "A",
    "CYT": "C",
    "GUA": "G",
    "URI": "U",
    "THY": "T",
    "PSU": "U",
    "H2U": "U",
    "5MU": "U",
    "OMG": "G",
    "7MG": "G",
    "1MA": "A",
    "M2G": "G",
}
_EXCLUDED_LIGANDS = {
    "HOH",
    "WAT",
    "DOD",
    "SO4",
    "PO4",
    "CL",
    "NA",
    "K",
    "MG",
    "MN",
    "CA",
    "ZN",
    "CO",
    "NI",
    "CU",
    "FE",
    "GOL",
    "EDO",
    "EOH",
    "PEG",
    "MPD",
    "MES",
    "TRS",
}
_BASE_PAIR_RULES: dict[tuple[str, str], tuple[tuple[str, str, float], ...]] = {
    ("A", "U"): (("N1", "N3", 3.6), ("N6", "O4", 3.6)),
    ("U", "A"): (("N3", "N1", 3.6), ("O4", "N6", 3.6)),
    ("A", "T"): (("N1", "N3", 3.6), ("N6", "O4", 3.6)),
    ("T", "A"): (("N3", "N1", 3.6), ("O4", "N6", 3.6)),
    ("G", "C"): (("O6", "N4", 3.6), ("N1", "N3", 3.6), ("N2", "O2", 3.6)),
    ("C", "G"): (("N4", "O6", 3.6), ("N3", "N1", 3.6), ("O2", "N2", 3.6)),
    ("G", "U"): (("O6", "N3", 3.6), ("N1", "O2", 3.6)),
    ("U", "G"): (("N3", "O6", 3.6), ("O2", "N1", 3.6)),
    ("G", "T"): (("O6", "N3", 3.6), ("N1", "O2", 3.6)),
    ("T", "G"): (("N3", "O6", 3.6), ("O2", "N1", 3.6)),
}
_MIN_PAIR_SEPARATION = 4
_C1_DISTANCE_RANGE = (5.0, 12.5)


def normalize_pdb_id(value: str | None) -> str | None:
    if not value:
        return None
    match = _PDB_ID.search(value.strip())
    if not match:
        return None
    return match.group(1).upper()


class PdbAnalysisAdapter:
    """Download and parse PDB structures for intake-time extraction."""

    def __init__(
        self,
        *,
        wget_command: str = "wget",
        base_url: str = "https://files.rcsb.org/download",
    ) -> None:
        self.wget_command = wget_command
        self.base_url = base_url.rstrip("/")

    def fetch(self, pdb_id: str, output_dir: str | Path) -> Path:
        normalized = normalize_pdb_id(pdb_id)
        if not normalized:
            raise RuntimeError(f"Invalid PDB ID: {pdb_id}")

        output_path = Path(output_dir) / f"{normalized}.pdb"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        url = f"{self.base_url}/{normalized}.pdb"
        wget_error: str | None = None

        wget_path = shutil.which(self.wget_command)
        if wget_path:
            try:
                subprocess.run(
                    [wget_path, "-q", "-O", str(output_path), url],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=90,
                )
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                stderr = (exc.stderr or "").strip()
                wget_error = f"wget failed while downloading {normalized}: {stderr or exc}"

        if not output_path.exists() or output_path.stat().st_size == 0:
            try:
                with urllib.request.urlopen(url, timeout=30) as response:
                    output_path.write_bytes(response.read())
            except urllib.error.URLError as exc:
                if wget_error:
                    raise RuntimeError(
                        f"{wget_error}; urllib fallback failed while downloading {normalized}: {exc}"
                    ) from exc
                raise RuntimeError(
                    f"Failed to download PDB {normalized}: {exc}"
                ) from exc

        if not output_path.exists() or output_path.stat().st_size == 0:
            raise RuntimeError(f"Downloaded file for {normalized} is empty.")
        return output_path

    def analyze(self, pdb_id: str, artifact_path: str | Path) -> PdbAnalysisResult:
        parser = self._make_parser()
        path = Path(artifact_path)
        try:
            structure = parser.get_structure(normalize_pdb_id(pdb_id) or pdb_id, str(path))
        except Exception as exc:
            raise RuntimeError(f"Failed to parse PDB file {path.name}: {exc}") from exc

        raw_text = path.read_text(encoding="utf-8", errors="ignore")
        title = self._parse_title(raw_text)
        hetnam = self._parse_hetnam(raw_text)

        chains = self._extract_chains(structure)
        ligands = self._extract_ligands(structure, hetnam)
        recommended_chain = chains[0].chain_id if len(chains) == 1 else None
        recommended_ligand = ligands[0].key if len(ligands) == 1 else None

        return PdbAnalysisResult(
            pdb_id=normalize_pdb_id(pdb_id) or pdb_id.upper(),
            title=title,
            artifact_path=str(path),
            nucleic_acid_chains=chains,
            ligands=ligands,
            recommended_chain_id=recommended_chain,
            recommended_ligand_key=recommended_ligand,
            needs_user_selection=len(chains) > 1 or len(ligands) > 1,
            semantic_status="unknown",
            semantic_note="",
            error="" if chains else "No nucleic acid chains were detected in the provided structure.",
        )

    def compare_sequence(self, user_sequence: str | None, pdb_sequence: str | None) -> str:
        if not user_sequence or not pdb_sequence:
            return "unknown"
        lhs = "".join(user_sequence.upper().split())
        rhs = "".join(pdb_sequence.upper().split())
        return "match" if lhs == rhs else "mismatch"

    def derive_secondary_structure(
        self,
        *,
        pdb_id: str,
        artifact_path: str | Path,
        chain_id: str,
    ) -> SecondaryStructure:
        parser = self._make_parser()
        path = Path(artifact_path)
        try:
            structure = parser.get_structure(normalize_pdb_id(pdb_id) or pdb_id, str(path))
        except Exception as exc:
            raise RuntimeError(f"Failed to parse PDB file {path.name}: {exc}") from exc

        residues = self._extract_chain_residues(structure, chain_id)
        if not residues:
            raise RuntimeError(f"PDB chain {chain_id} did not contain a usable nucleic-acid sequence.")

        sequence = "".join(base for _residue_id, base, _residue in residues)
        candidate_scores: dict[tuple[int, int], float] = {}
        for left_idx, (_left_residue_id, left_base, left_residue) in enumerate(residues):
            for right_idx in range(left_idx + _MIN_PAIR_SEPARATION, len(residues)):
                _right_residue_id, right_base, right_residue = residues[right_idx]
                score = self._score_base_pair(
                    left_base=left_base,
                    left_residue=left_residue,
                    right_base=right_base,
                    right_residue=right_residue,
                )
                if score > 0:
                    candidate_scores[(left_idx, right_idx)] = score

        pairs = self._select_non_crossing_pairs(len(residues), candidate_scores)
        dot_bracket = ["." for _ in residues]
        for left_idx, right_idx in pairs:
            dot_bracket[left_idx] = "("
            dot_bracket[right_idx] = ")"

        return SecondaryStructure(
            sequence=sequence,
            dot_bracket="".join(dot_bracket),
            mfe=0.0,
            features={
                "source": "pdb",
                "pdb_id": normalize_pdb_id(pdb_id) or pdb_id.upper(),
                "chain_id": chain_id,
                "artifact_path": str(path),
                "pair_count": len(pairs),
            },
        )

    def _make_parser(self):
        try:
            from Bio.PDB import PDBParser
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Biopython is required for PDB analysis. Install `biopython` on the server before running this workflow."
            ) from exc
        return PDBParser(QUIET=True)

    @staticmethod
    def _parse_title(raw_text: str) -> str:
        lines = [
            line[10:].strip()
            for line in raw_text.splitlines()
            if line.startswith("TITLE ")
        ]
        return " ".join(lines).strip()

    @staticmethod
    def _parse_hetnam(raw_text: str) -> dict[str, str]:
        names: dict[str, list[str]] = {}
        for line in raw_text.splitlines():
            if not line.startswith("HETNAM"):
                continue
            identifier = line[11:14].strip().upper()
            text = line[15:].strip()
            if not identifier or not text:
                continue
            names.setdefault(identifier, []).append(text)
        return {key: " ".join(parts).strip() for key, parts in names.items()}

    def _extract_chains(self, structure) -> list[PdbChainCandidate]:
        model = next(structure.get_models(), None)
        if model is None:
            return []

        candidates: list[PdbChainCandidate] = []
        for chain in model:
            sequence: list[str] = []
            seen_positions: set[tuple[str, int, str]] = set()
            types: set[str] = set()
            for residue in chain:
                hetflag = residue.id[0].strip()
                if hetflag.startswith("H"):
                    continue
                code = self._map_nucleotide_code(residue.resname)
                if code is None:
                    continue
                position_key = (chain.id, residue.id[1], residue.resname.strip().upper())
                if position_key in seen_positions:
                    continue
                seen_positions.add(position_key)
                sequence.append(code)
                types.add("rna" if code == "U" else "dna" if code == "T" else "nucleic_acid")
            if not sequence:
                continue
            molecule_type = "rna" if "rna" in types and "dna" not in types else "dna" if "dna" in types and "rna" not in types else "mixed_nucleic_acid"
            candidates.append(
                PdbChainCandidate(
                    chain_id=(chain.id or "?").strip() or "?",
                    sequence="".join(sequence),
                    residue_count=len(sequence),
                    molecule_type=molecule_type,
                )
            )
        return candidates

    def _extract_ligands(self, structure, hetnam: dict[str, str]) -> list[PdbLigandCandidate]:
        model = next(structure.get_models(), None)
        if model is None:
            return []

        seen: set[str] = set()
        ligands: list[PdbLigandCandidate] = []
        for chain in model:
            for residue in chain:
                hetflag = residue.id[0].strip()
                if not hetflag.startswith("H"):
                    continue
                resname = residue.resname.strip().upper()
                if resname in _EXCLUDED_LIGANDS:
                    continue
                atom_count = len(list(residue.get_atoms()))
                if atom_count < 4:
                    continue
                key = f"{(chain.id or '?').strip() or '?'}:{resname}:{residue.id[1]}"
                if key in seen:
                    continue
                seen.add(key)
                ligands.append(
                    PdbLigandCandidate(
                        key=key,
                        identifier=resname,
                        display_name=hetnam.get(resname, resname),
                        chain_id=(chain.id or "?").strip() or "?",
                        residue_number=int(residue.id[1]),
                        atom_count=atom_count,
                    )
                )
        return ligands

    def _extract_chain_residues(self, structure, chain_id: str) -> list[tuple[str, str, object]]:
        model = next(structure.get_models(), None)
        if model is None:
            return []

        normalized_chain_id = (chain_id or "").strip() or "?"
        for chain in model:
            current_chain_id = (getattr(chain, "id", "?") or "?").strip() or "?"
            if current_chain_id != normalized_chain_id:
                continue
            residues: list[tuple[str, str, object]] = []
            seen_positions: set[tuple[str, int, str, str]] = set()
            for residue in chain:
                hetflag = residue.id[0].strip()
                if hetflag.startswith("H"):
                    continue
                base = self._map_nucleotide_code(residue.resname)
                if base is None:
                    continue
                insertion_code = residue.id[2].strip() if len(residue.id) > 2 else ""
                position_key = (
                    current_chain_id,
                    residue.id[1],
                    insertion_code,
                    residue.resname.strip().upper(),
                )
                if position_key in seen_positions:
                    continue
                seen_positions.add(position_key)
                residue_label = f"{current_chain_id}:{residue.id[1]}{insertion_code}".strip()
                residues.append((residue_label, base, residue))
            return residues
        return []

    def _score_base_pair(
        self,
        *,
        left_base: str,
        left_residue,
        right_base: str,
        right_residue,
    ) -> float:
        rules = _BASE_PAIR_RULES.get((left_base, right_base))
        if rules is None:
            return 0.0

        hydrogen_bond_bonus = 0.0
        for left_atom_name, right_atom_name, max_distance in rules:
            left_coord = self._get_atom_coord(left_residue, left_atom_name)
            right_coord = self._get_atom_coord(right_residue, right_atom_name)
            if left_coord is None or right_coord is None:
                return 0.0
            distance = math.dist(left_coord, right_coord)
            if distance > max_distance:
                return 0.0
            hydrogen_bond_bonus += max_distance - distance

        left_c1 = self._get_atom_coord(left_residue, "C1'")
        right_c1 = self._get_atom_coord(right_residue, "C1'")
        if left_c1 is None or right_c1 is None:
            return 0.0

        c1_distance = math.dist(left_c1, right_c1)
        if not (_C1_DISTANCE_RANGE[0] <= c1_distance <= _C1_DISTANCE_RANGE[1]):
            return 0.0

        return float(len(rules)) + hydrogen_bond_bonus

    @staticmethod
    def _get_atom_coord(residue, atom_name: str) -> tuple[float, float, float] | None:
        candidate_names = {
            atom_name,
            atom_name.replace("'", "*"),
            atom_name.replace("*", "'"),
        }

        for candidate in candidate_names:
            try:
                atom = residue[candidate]
            except Exception:
                atom = None
            if atom is None:
                continue
            coord = PdbAnalysisAdapter._coerce_coord(atom)
            if coord is not None:
                return coord

        for atom in residue:
            try:
                current_name = atom.get_name()
            except Exception:
                current_name = getattr(atom, "id", None) or getattr(atom, "name", None)
            if current_name not in candidate_names:
                continue
            coord = PdbAnalysisAdapter._coerce_coord(atom)
            if coord is not None:
                return coord
        return None

    @staticmethod
    def _coerce_coord(atom) -> tuple[float, float, float] | None:
        coord = None
        try:
            coord = atom.get_coord()
        except Exception:
            coord = getattr(atom, "coord", None)
        if coord is None:
            return None
        try:
            x, y, z = coord
        except Exception:
            return None
        return (float(x), float(y), float(z))

    def _select_non_crossing_pairs(
        self,
        length: int,
        candidate_scores: dict[tuple[int, int], float],
    ) -> list[tuple[int, int]]:
        @lru_cache(maxsize=None)
        def best(start: int, end: int) -> float:
            if start >= end:
                return 0.0

            score = max(best(start + 1, end), best(start, end - 1))
            pair_score = candidate_scores.get((start, end))
            if pair_score is not None:
                score = max(score, best(start + 1, end - 1) + pair_score)
            for split in range(start + 1, end):
                score = max(score, best(start, split) + best(split + 1, end))
            return score

        def trace(start: int, end: int) -> list[tuple[int, int]]:
            if start >= end:
                return []

            current = best(start, end)
            if current == best(start + 1, end):
                return trace(start + 1, end)
            if current == best(start, end - 1):
                return trace(start, end - 1)

            pair_score = candidate_scores.get((start, end))
            if pair_score is not None and current == best(start + 1, end - 1) + pair_score:
                return trace(start + 1, end - 1) + [(start, end)]

            for split in range(start + 1, end):
                if current == best(start, split) + best(split + 1, end):
                    return trace(start, split) + trace(split + 1, end)
            return []

        if length <= 1 or not candidate_scores:
            return []
        return trace(0, length - 1)

    @staticmethod
    def _map_nucleotide_code(resname: str) -> str | None:
        normalized = resname.strip().upper()
        if normalized in _NUCLEOTIDE_CODES:
            return _NUCLEOTIDE_CODES[normalized]
        if normalized.startswith("D") and len(normalized) == 2 and normalized[1] in "ACGTU":
            return normalized[1]
        if len(normalized) == 1 and normalized in {"A", "C", "G", "U", "T"}:
            return normalized
        return None
