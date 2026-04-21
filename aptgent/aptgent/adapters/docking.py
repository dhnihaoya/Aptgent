from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from aptgent.domain.models import CandidateSequence, DockingResult, TargetMolecule


class VinaAdapter:
    """Real AutoDock Vina adapter via subprocess."""

    @staticmethod
    def output_path(work_dir: str | Path, candidate_id: str) -> Path:
        """Canonical output PDBQT path for a docked candidate."""
        return Path(work_dir) / f"output_{candidate_id}.pdbqt"

    def __init__(
        self,
        executable: str = "vina",
        exhaustiveness: int = 8,
        num_modes: int = 9,
        energy_range: float = 3.0,
        lazy: bool = False,
    ) -> None:
        self.executable = executable
        self.exhaustiveness = exhaustiveness
        self.num_modes = num_modes
        self.energy_range = energy_range
        if not lazy:
            self._check_binary()

    def _check_binary(self) -> None:
        if shutil.which(self.executable) is None:
            raise FileNotFoundError(
                f"{self.executable} not found in PATH. "
                "Please install AutoDock Vina (https://github.com/ccsb-scripps/AutoDock-Vina)."
            )

    def prepare_ligand(self, smiles: str, output_dir: str | Path) -> Path:
        """Convert SMILES to PDBQT using meeko + RDKit, write to output_dir.

        Returns path to the generated PDBQT file.
        """
        from meeko import MoleculePreparation, PDBQTWriterLegacy
        from rdkit import Chem
        from rdkit.Chem import AllChem

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            raise ValueError(f"RDKit could not parse SMILES: {smiles}")
        mol = Chem.AddHs(mol)
        code = AllChem.EmbedMolecule(mol, randomSeed=42)
        if code == -1:
            raise ValueError(f"Could not generate 3D coordinates for: {smiles}")
        AllChem.MMFFOptimizeMolecule(mol)

        mk_prep = MoleculePreparation()
        molsetup_list = mk_prep(mol)
        pdbqt_string = PDBQTWriterLegacy.write_string(molsetup_list[0])[0]

        # Sanitize SMILES for filename
        safe = re.sub(r"[^a-zA-Z0-9]", "_", smiles)[:40]
        path = output_dir / f"ligand_{safe}.pdbqt"
        path.write_text(pdbqt_string, encoding="utf-8")
        return path

    def run_single(
        self,
        receptor_pdbqt: str | Path,
        ligand_pdbqt: str | Path,
        center: list[float],
        size: list[float],
        output_pdbqt: str | Path | None = None,
        cpu: int | None = None,
        seed: int | None = None,
        timeout: int = 3600,
    ) -> DockingResult:
        """Run Vina for a single receptor-ligand pair.

        Args:
            receptor_pdbqt: Path to receptor PDBQT file.
            ligand_pdbqt: Path to ligand PDBQT file.
            center: [x, y, z] grid box center in Angstroms.
            size: [x, y, z] grid box size in Angstroms.
            output_pdbqt: Optional path for output poses.
            cpu: Number of CPUs to use (None = auto).
            seed: Random seed for reproducibility.
            timeout: Maximum seconds to wait for Vina (default 3600).

        Returns:
            DockingResult with the best mode affinity as docking_score.
        """
        if not isinstance(center, (list, tuple)) or len(center) < 3:
            raise ValueError(f"center must have 3 elements [x, y, z], got {center!r}")
        if not isinstance(size, (list, tuple)) or len(size) < 3:
            raise ValueError(f"size must have 3 elements [x, y, z], got {size!r}")

        cmd = [
            self.executable,
            "--receptor", str(receptor_pdbqt),
            "--ligand", str(ligand_pdbqt),
            "--center_x", str(center[0]),
            "--center_y", str(center[1]),
            "--center_z", str(center[2]),
            "--size_x", str(size[0]),
            "--size_y", str(size[1]),
            "--size_z", str(size[2]),
            "--exhaustiveness", str(self.exhaustiveness),
            "--num_modes", str(self.num_modes),
            "--energy_range", str(self.energy_range),
        ]
        if output_pdbqt is not None:
            cmd.extend(["--out", str(output_pdbqt)])
        if cpu is not None:
            cmd.extend(["--cpu", str(cpu)])
        if seed is not None:
            cmd.extend(["--seed", str(seed)])

        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, check=False, timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"Vina timed out after {timeout}s"
            ) from exc
        if proc.returncode != 0:
            raise RuntimeError(f"Vina failed (exit {proc.returncode}): {proc.stderr}")

        return self._parse_output(proc.stdout, ligand_pdbqt)

    def run_batch(
        self,
        candidates: list[CandidateSequence],
        target: TargetMolecule,
        receptor_pdbqt: str | Path,
        center: list[float],
        size: list[float],
        work_dir: str | Path | None = None,
        cpu: int | None = None,
        seed: int | None = None,
        per_ligand_timeout: int | None = None,
    ) -> list[DockingResult]:
        """Run Vina for each candidate against the target molecule.

        For each candidate, the target SMILES is converted to PDBQT via meeko,
        then Vina is called with the provided receptor and grid box.

        Args:
            candidates: List of candidate sequences.
            target: Target molecule with resolved SMILES.
            receptor_pdbqt: Path to receptor PDBQT file.
            center: Grid box center [x, y, z].
            size: Grid box size [x, y, z].
            work_dir: Directory for temp files (default: system temp).
            cpu: Number of CPUs per Vina run.
            seed: Random seed for reproducibility.
            per_ligand_timeout: Max seconds per ligand (default: 1800).

        Returns:
            List of DockingResult, one per candidate.
        """
        self._check_binary()

        if not target.smiles:
            raise ValueError("Target molecule must have a resolved SMILES string.")

        created_tmp = False
        if work_dir is None:
            work_dir = Path(tempfile.mkdtemp(prefix="vina_"))
            created_tmp = True
        else:
            work_dir = Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)

        try:
            ligand_path = self.prepare_ligand(target.smiles, work_dir / "ligands")

            results: list[DockingResult] = []
            for i, cand in enumerate(candidates):
                cand_id = cand.candidate_id or f"cand_{i}"
                out_path = self.output_path(work_dir, cand_id)
                try:
                    result = self.run_single(
                        receptor_pdbqt=receptor_pdbqt,
                        ligand_pdbqt=ligand_path,
                        center=center,
                        size=size,
                        output_pdbqt=out_path,
                        cpu=cpu,
                        seed=seed,
                        timeout=per_ligand_timeout or 1800,
                    )
                    result.candidate_id = cand_id
                    results.append(result)
                except Exception as e:
                    results.append(
                        DockingResult(
                            candidate_id=cand_id,
                            docking_score=None,
                            status=f"error: {e}",
                            raw_outputs={"error": str(e)},
                        )
                    )
        finally:
            if created_tmp:
                shutil.rmtree(work_dir, ignore_errors=True)

        return results

    def _parse_output(self, stdout: str, ligand_ref: Any = None) -> DockingResult:
        """Parse Vina stdout to extract the best binding affinity."""
        # Match lines like: "   1       -13.23       0.000       0.000"
        pattern = r"^\s*(\d+)\s+(-?\d+\.?\d*)\s+"
        matches = re.findall(pattern, stdout, re.MULTILINE)
        if not matches:
            return DockingResult(
                candidate_id="",
                docking_score=None,
                status="no_results",
                raw_outputs={"stdout": stdout},
            )

        best_affinity = float(matches[0][1])
        all_modes = [
            {"mode": int(m[0]), "affinity": float(m[1])} for m in matches
        ]
        return DockingResult(
            candidate_id="",
            docking_score=best_affinity,
            status="completed",
            raw_outputs={
                "modes": all_modes,
                "exhaustiveness": self.exhaustiveness,
                "num_modes": self.num_modes,
            },
        )
class HardwareProbeAdapter:
    """Simple runtime hardware probe for docking planning."""

    def probe(self) -> dict[str, object]:
        cpu_count = os.cpu_count() or 1
        mem_bytes: int | None = None
        try:
            import psutil

            mem_bytes = psutil.virtual_memory().total
        except Exception:
            pass

        return {
            "cpu_count": cpu_count,
            "memory_bytes": mem_bytes,
            "memory_gb": round(mem_bytes / (1024 ** 3), 2) if mem_bytes else None,
        }
