"""Receptor preparation: DNA<->RNA, hydrogen addition, PDB->PDBQT, bbox.

This adapter encapsulates the headless equivalent of the manual ADT GUI
workflow described in Aptamers-2026.5.4.docx §2.4.4:

- T <-> U sequence alphabet conversion (RNAComposer accepts RNA only)
- Programmatic equivalent of MOE's "U->T + ribose->deoxyribose" by removing
  O2' atoms and renaming residues
- Hydrogen addition + Gasteiger partial charges (Open Babel CLI), equivalent
  to ADT's `Edit -> Hydrogens -> Add`
- Bounding-box derivation that "covers the entire aptamer" with padding
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

_log = logging.getLogger(__name__)


# Standard RNA residue names that may appear in a RNAComposer PDB.
_RNA_RESIDUES = {"A", "U", "G", "C"}
_RNA_TO_DNA = {"A": "DA", "U": "DT", "G": "DG", "C": "DC"}
_ALL_RIBOSE_O2_ATOMS = {"O2'", "O2*", "HO2'", "HO2*", "H2'", "H2*"}


@dataclass(frozen=True)
class BoundingBox:
    """Axis-aligned box covering an aptamer; size already includes padding."""

    center: tuple[float, float, float]
    size: tuple[float, float, float]
    padding: float
    atom_count: int

    def as_dict(self) -> dict[str, list[float]]:
        return {
            "center": list(self.center),
            "size": list(self.size),
        }


def dna_to_rna(sequence: str) -> str:
    """Convert DNA letters to RNA (T -> U). Preserves case and other chars."""
    return sequence.replace("T", "U").replace("t", "u")


def rna_to_dna(sequence: str) -> str:
    """Convert RNA letters to DNA (U -> T). Preserves case and other chars."""
    return sequence.replace("U", "T").replace("u", "t")


def revert_ribose_to_deoxyribose(pdb_text: str) -> str:
    """Program-equivalent of MOE's "RNA -> DNA" step.

    Walks each ATOM/HETATM line in *pdb_text*:
    1. Drops every 2'-OH related atom (O2', HO2', H2').
    2. Renames the residue from A/U/G/C to DA/DT/DG/DC.

    The result is a chemically reasonable DNA model derived from the
    RNAComposer RNA prediction. It is not a true energy-minimized structure;
    consider this an analog of the MOE manual conversion described in the
    paper, which we cannot script directly.
    """
    out: list[str] = []
    for raw_line in pdb_text.splitlines():
        if len(raw_line) < 17 or not raw_line.startswith(("ATOM", "HETATM")):
            out.append(raw_line)
            continue

        atom_name = raw_line[12:16].strip()
        if atom_name in _ALL_RIBOSE_O2_ATOMS:
            continue

        res_name = raw_line[17:20].strip()
        if res_name in _RNA_RESIDUES:
            new_res = _RNA_TO_DNA[res_name]
            new_line = raw_line[:17] + f"{new_res:>3}" + raw_line[20:]
            out.append(new_line)
            continue

        out.append(raw_line)
    if pdb_text.endswith("\n"):
        return "\n".join(out) + "\n"
    return "\n".join(out)


class ReceptorPreparationAdapter:
    """Headless equivalent of ADT receptor preparation.

    Configurable via constructor:

    - ``obabel_command``: path / name of the Open Babel binary
      (default ``"obabel"``). Required for the PDB -> PDBQT step.
    - ``default_padding``: Angstroms added to every axis of the
      aptamer-bounding box (default 4.0). The center is always the geometric
      mid-point of all heavy atoms.
    """

    def __init__(
        self,
        *,
        obabel_command: str = "obabel",
        default_padding: float = 4.0,
    ) -> None:
        self.obabel_command = obabel_command
        self.default_padding = default_padding

    # ------------------------------------------------------------------
    # Sequence helpers (thin pass-throughs so callers don't import module fns)
    # ------------------------------------------------------------------

    @staticmethod
    def dna_to_rna(sequence: str) -> str:
        return dna_to_rna(sequence)

    @staticmethod
    def rna_to_dna(sequence: str) -> str:
        return rna_to_dna(sequence)

    @staticmethod
    def revert_ribose_to_deoxyribose(pdb_text: str) -> str:
        return revert_ribose_to_deoxyribose(pdb_text)

    # ------------------------------------------------------------------
    # PDB -> PDBQT (hydrogen addition + Gasteiger charges)
    # ------------------------------------------------------------------

    def prepare_pdbqt(
        self,
        pdb_path: str | Path,
        output_path: str | Path,
        *,
        treat_as_dna: bool = True,
    ) -> Path:
        """Convert a ``.pdb`` aptamer file to PDBQT with hydrogens.

        This invokes ``obabel <in> -O <out> -xr -h --partialcharge gasteiger``,
        which:

        - adds polar / all hydrogens (``-h``), equivalent to ADT's
          ``Edit -> Hydrogens -> Add``
        - assigns Gasteiger partial charges
        - emits a rigid receptor (``-xr``) so Vina treats the aptamer as a
          rigid macromolecule

        Raises ``FileNotFoundError`` if Open Babel is not available, or
        ``RuntimeError`` if the conversion fails.
        """
        pdb_path = Path(pdb_path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if not pdb_path.exists():
            raise FileNotFoundError(f"Input PDB not found: {pdb_path}")

        if shutil.which(self.obabel_command) is None:
            raise FileNotFoundError(
                f"{self.obabel_command} not found in PATH. Install Open Babel "
                "(conda-forge) or set APTGENT_OBABEL."
            )

        if treat_as_dna:
            pdb_text = pdb_path.read_text(encoding="utf-8", errors="replace")
            if _looks_like_rna(pdb_text):
                pdb_text = revert_ribose_to_deoxyribose(pdb_text)
                pdb_path = output_path.with_suffix(".dna.pdb")
                pdb_path.write_text(pdb_text, encoding="utf-8")

        cmd = [
            self.obabel_command,
            str(pdb_path),
            "-O",
            str(output_path),
            "-xr",
            "-h",
            "--partialcharge",
            "gasteiger",
        ]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, check=False, timeout=120
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"Open Babel timed out converting {pdb_path}") from exc

        if proc.returncode != 0 or not output_path.exists():
            raise RuntimeError(
                f"Open Babel failed for {pdb_path}: {proc.stderr.strip()}"
            )
        return output_path

    # ------------------------------------------------------------------
    # Bounding box from a PDB/PDBQT
    # ------------------------------------------------------------------

    def compute_box(
        self,
        structure_path: str | Path,
        *,
        padding: float | None = None,
    ) -> BoundingBox:
        """Compute the aptamer-covering search box from a PDB/PDBQT file."""
        path = Path(structure_path)
        if not path.exists():
            raise FileNotFoundError(f"Structure file not found: {path}")
        pad = padding if padding is not None else self.default_padding
        coords = list(_iter_atom_coordinates(path.read_text(encoding="utf-8")))
        if not coords:
            raise ValueError(f"No ATOM/HETATM records found in {path}")
        xs, ys, zs = zip(*coords)
        cx = (min(xs) + max(xs)) / 2.0
        cy = (min(ys) + max(ys)) / 2.0
        cz = (min(zs) + max(zs)) / 2.0
        sx = (max(xs) - min(xs)) + 2.0 * pad
        sy = (max(ys) - min(ys)) + 2.0 * pad
        sz = (max(zs) - min(zs)) + 2.0 * pad
        return BoundingBox(
            center=(round(cx, 3), round(cy, 3), round(cz, 3)),
            size=(round(sx, 3), round(sy, 3), round(sz, 3)),
            padding=pad,
            atom_count=len(coords),
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _looks_like_rna(pdb_text: str) -> bool:
    """Heuristic: returns True if a PDB body contains an RNA residue name."""
    for line in pdb_text.splitlines():
        if line.startswith(("ATOM", "HETATM")) and len(line) >= 20:
            res = line[17:20].strip()
            if res in _RNA_RESIDUES:
                return True
    return False


def _iter_atom_coordinates(pdb_text: str) -> Iterable[tuple[float, float, float]]:
    for raw_line in pdb_text.splitlines():
        if not raw_line.startswith(("ATOM", "HETATM")):
            continue
        if len(raw_line) < 54:
            continue
        try:
            x = float(raw_line[30:38])
            y = float(raw_line[38:46])
            z = float(raw_line[46:54])
        except ValueError:
            continue
        yield x, y, z


# ---------------------------------------------------------------------------
# Sequence export & manual structure-directory scanning
# ---------------------------------------------------------------------------


def export_top_k_sequences(
    candidates: list[tuple[str, str]],
    output_dir: str | Path,
) -> Path:
    """Write ``<candidate_id>.fasta`` + ``sequences.tsv`` for the top-K.

    Files are named directly after the candidate id (so ``cand_0`` produces
    ``cand_0.fasta``, matching the convention the user is expected to use
    when uploading prepared structures back).

    Args:
        candidates: A list of ``(candidate_id, sequence)`` pairs.
        output_dir: Target directory; will be created if missing.

    Returns the absolute path of the output directory.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    tsv = out / "sequences.tsv"
    with tsv.open("w", encoding="utf-8") as fh:
        fh.write("candidate_id\tsequence\n")
        for cand_id, seq in candidates:
            fh.write(f"{cand_id}\t{seq}\n")
            fasta = out / f"{cand_id}.fasta"
            fasta.write_text(f">{cand_id}\n{seq}\n", encoding="utf-8")
    return out.resolve()


def scan_structure_directory(
    directory: str | Path,
    candidate_ids: list[str],
) -> dict[str, dict[str, str]]:
    """Scan *directory* for files matching ``<candidate_id>.{pdb,pdbqt}``.

    Returns a mapping ``{candidate_id: {"pdb": path, "pdbqt": path}}``;
    missing entries indicate the user has not provided that candidate yet.
    """
    base = Path(directory)
    if not base.exists() or not base.is_dir():
        return {}
    matches: dict[str, dict[str, str]] = {}
    for cand_id in candidate_ids:
        per_cand: dict[str, str] = {}
        pdbqt = base / f"{cand_id}.pdbqt"
        pdb = base / f"{cand_id}.pdb"
        if pdbqt.exists():
            per_cand["pdbqt"] = str(pdbqt.resolve())
        if pdb.exists():
            per_cand["pdb"] = str(pdb.resolve())
        if per_cand:
            matches[cand_id] = per_cand
    return matches
