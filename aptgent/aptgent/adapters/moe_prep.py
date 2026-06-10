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
        default_padding: float = 0.0,
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
        on_file_done: Callable[[int, int], None] | None = None,
    ) -> dict[str, Path]:
        """Run ``moebatch`` on RNA PDBs to produce minimized DNA PDBs.

        Each candidate is processed with its **own** ``moebatch`` invocation
        over an isolated temporary directory that contains only that one
        structure.  RNAComposer (a public scraper) inevitably produces a few
        malformed structures; running per-file means one bad PDB only fails its
        own conversion instead of aborting the whole batch.  Successful
        conversions are always returned even when some candidates fail.

        Args:
            input_dir: Directory containing ``{cand_id}.pdb`` RNA files.
            output_dir: Directory for MOE-processed DNA PDB output.
            candidate_ids: IDs to process (must have corresponding ``.pdb`` in input_dir).
            on_progress: Optional callback for progress messages.
            on_file_done: Optional callback invoked after each candidate with
                ``(completed_count, total)`` so callers can drive a progress bar.

        Returns:
            Mapping ``{cand_id: output_pdb_path}`` for successfully processed files.

        Raises:
            FileNotFoundError: If ``moebatch`` is not available.
            RuntimeError: Only if *every* candidate failed (no output produced).
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

        total = len(candidate_ids)
        results: dict[str, Path] = {}
        failures: list[tuple[str, str]] = []
        resolved_input = input_dir.resolve()
        resolved_output = output_dir.resolve()

        for index, cand_id in enumerate(candidate_ids, start=1):
            src = resolved_input / f"{cand_id}.pdb"
            if not src.exists():
                failures.append((cand_id, "input RNA PDB missing"))
                if on_file_done:
                    on_file_done(index, total)
                continue

            if on_progress:
                on_progress(f"MOE processing {index}/{total}: {cand_id}")

            try:
                out_path = self._run_one(script, src, cand_id, resolved_output)
            except Exception as exc:  # noqa: BLE001 — isolate per-file failures
                failures.append((cand_id, str(exc)))
                if on_progress:
                    on_progress(f"MOE failed for {cand_id}: {exc}")
                if on_file_done:
                    on_file_done(index, total)
                continue

            results[cand_id] = out_path
            if on_file_done:
                on_file_done(index, total)

        if not results:
            detail = "; ".join(f"{cid}: {msg}" for cid, msg in failures[:5])
            raise RuntimeError(
                f"moebatch failed for all {total} structures. {detail}"
            )

        if on_progress:
            on_progress(f"MOE processed {len(results)}/{total} structures.")

        return results

    def _run_one(
        self,
        script: Path,
        src: Path,
        cand_id: str,
        output_dir: Path,
    ) -> Path:
        """Run ``moebatch`` for a single structure in an isolated input dir.

        Raises ``RuntimeError`` on failure (non-zero exit with no output, a
        timeout, or a missing/empty output file).
        """
        with tempfile.TemporaryDirectory(prefix="aptgent_moe_") as tmp:
            tmp_dir = Path(tmp)
            # Absolute target: moebatch may run with a different cwd, so a
            # relative symlink would point at a non-existent path and MOE would
            # exit 0 without writing any output.
            (tmp_dir / f"{cand_id}.pdb").symlink_to(src.resolve())

            cmd = [self.moebatch_command, "-licwait", "-run", str(script)]
            env = {
                **os.environ,
                "APT_IN": str(tmp_dir.resolve()),
                "APT_OUT": str(output_dir.resolve()),
            }

            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=self.timeout_per_file,
                    env=env,
                )
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(
                    f"moebatch timed out after {self.timeout_per_file}s"
                ) from exc

        out_path = output_dir / f"{cand_id}.pdb"
        if not (out_path.exists() and out_path.stat().st_size > 0):
            detail = proc.stderr.strip() or proc.stdout.strip() or "no output file produced"
            raise RuntimeError(
                f"moebatch failed (exit {proc.returncode}): "
                f"{detail[:500]}"
            )
        return out_path

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
