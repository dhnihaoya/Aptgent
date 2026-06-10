"""MOE-based receptor preparation: RNA→DNA conversion + AmberEHT minimization.

Uses ``moebatch`` (Molecular Operating Environment headless mode) to convert
RNAComposer RNA models into energy-minimized DNA aptamer structures via a
bundled SVL script.  After MOE processing, the output PDB is converted to
PDBQT via Open Babel (same as the non-MOE path).

Requires MOE to be installed and ``moebatch`` available in PATH (or configured
via ``APTGENT_MOEBATCH``).  Falls back gracefully when unavailable.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

from aptgent.adapters.receptor_prep import ReceptorPreparationAdapter


class MoePreparationAdapter:
    """MOE-based receptor preparation via ``moebatch``.

    The bundled SVL script (``moe_rna2dna_min.svl``) performs:
    1. Load AmberEHT force field
    2. Convert RNA residues to DNA (U/DU → DT, ribose → deoxyribose)
    3. Energy minimize with all-heavy-atom tether restraint (sdev 0.5 Å)
    4. Write output PDB

    Configuration via ``tools.toml`` ``[moe]`` section or env vars.
    """

    def __init__(
        self,
        *,
        moebatch_command: str = "moebatch",
        obabel_command: str = "obabel",
        default_padding: float = 4.0,
        timeout_per_file: int = 600,
    ) -> None:
        self.moebatch_command = moebatch_command
        self.obabel_command = obabel_command
        self.default_padding = default_padding
        self.timeout_per_file = timeout_per_file
        self._receptor_prep = ReceptorPreparationAdapter(
            obabel_command=obabel_command,
            default_padding=default_padding,
        )

    @staticmethod
    def is_available(moebatch_command: str = "moebatch") -> bool:
        return shutil.which(moebatch_command) is not None

    @property
    def svl_script_path(self) -> Path:
        return (
            Path(__file__).resolve().parent.parent
            / "resources" / "scripts" / "moe_rna2dna_min.svl"
        )

    def convert_rna_to_dna_minimize(
        self,
        input_dir: Path,
        output_dir: Path,
        candidate_ids: list[str],
        *,
        on_progress: Callable[[str], None] | None = None,
    ) -> dict[str, Path]:
        """Run ``moebatch`` on RNA PDBs to produce minimized DNA PDBs.

        Creates an isolated temporary directory containing only symlinks to the
        requested candidate files, so the SVL script cannot see stale or
        unrelated ``.pdb`` files.  Also passes ``APT_CANDIDATES`` for
        server-side filtering (defense in depth).

        Args:
            input_dir: Directory containing ``{cand_id}.pdb`` RNA files.
            output_dir: Directory for MOE-processed DNA PDB output.
            candidate_ids: IDs to process (must have corresponding ``.pdb`` in input_dir).
            on_progress: Optional callback for progress messages.

        Returns:
            Mapping ``{cand_id: output_pdb_path}`` for successfully processed files.

        Raises:
            FileNotFoundError: If ``moebatch`` is not available.
            RuntimeError: If ``moebatch`` fails or output files are missing.
        """
        if not self.is_available(self.moebatch_command):
            raise FileNotFoundError(
                f"{self.moebatch_command} not found in PATH. "
                "Install MOE or set APTGENT_MOEBATCH."
            )

        script = self.svl_script_path
        if not script.exists():
            raise FileNotFoundError(f"SVL script not found: {script}")

        output_dir.mkdir(parents=True, exist_ok=True)

        total_timeout = self.timeout_per_file * max(len(candidate_ids), 1)

        if on_progress:
            on_progress(f"Running MOE on {len(candidate_ids)} structures...")

        candidate_files = ",".join(f"{cid}.pdb" for cid in candidate_ids)

        with tempfile.TemporaryDirectory(prefix="aptgent_moe_") as tmp:
            tmp_dir = Path(tmp)
            for cid in candidate_ids:
                src = input_dir / f"{cid}.pdb"
                if src.exists():
                    (tmp_dir / f"{cid}.pdb").symlink_to(src)

            cmd = [
                self.moebatch_command,
                "-licwait",
                "-run", str(script),
            ]
            env = {
                **os.environ,
                "APT_IN": str(tmp_dir),
                "APT_OUT": str(output_dir),
                "APT_CANDIDATES": candidate_files,
            }

            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=total_timeout,
                    env=env,
                )
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(
                    f"moebatch timed out after {total_timeout}s"
                ) from exc

        if proc.returncode != 0 and not any(
            (output_dir / f"{cid}.pdb").exists() for cid in candidate_ids
        ):
            raise RuntimeError(
                f"moebatch failed (exit {proc.returncode}): "
                f"{proc.stderr.strip()[:500]}"
            )

        results: dict[str, Path] = {}
        for cand_id in candidate_ids:
            out_path = output_dir / f"{cand_id}.pdb"
            if out_path.exists() and out_path.stat().st_size > 0:
                results[cand_id] = out_path

        if not results:
            raise RuntimeError(
                f"moebatch produced no output files. "
                f"stderr: {proc.stderr.strip()[:500]}"
            )

        if on_progress:
            on_progress(
                f"MOE processed {len(results)}/{len(candidate_ids)} structures."
            )

        return results

    def prepare_pdbqt(
        self,
        pdb_path: str | Path,
        output_path: str | Path,
    ) -> Path:
        """Convert MOE-output DNA PDB to PDBQT (hydrogens + Gasteiger charges)."""
        return self._receptor_prep.prepare_pdbqt(
            pdb_path, output_path, treat_as_dna=False,
        )

    def compute_box(
        self,
        structure_path: str | Path,
        *,
        padding: float | None = None,
    ):
        """Compute bounding box from a PDB/PDBQT structure."""
        return self._receptor_prep.compute_box(structure_path, padding=padding)
