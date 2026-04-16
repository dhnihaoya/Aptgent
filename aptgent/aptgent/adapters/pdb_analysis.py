from __future__ import annotations

import logging
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from aptgent.domain.models import (
    PdbAnalysisResult,
    PdbChainCandidate,
    PdbLigandCandidate,
)

_log = logging.getLogger(__name__)

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
