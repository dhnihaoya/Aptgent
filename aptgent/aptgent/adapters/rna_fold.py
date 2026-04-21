from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from aptgent.domain.models import SecondaryStructure


def _find_param_file(name: str) -> str | None:
    """Locate a ViennaRNA parameter file via ``$CONDA_PREFIX`` or common paths."""
    candidates: list[Path] = []
    prefix = os.environ.get("CONDA_PREFIX")
    if prefix:
        candidates.append(Path(prefix) / "share" / "ViennaRNA" / name)
    candidates.append(Path.home() / ".conda" / "envs" / "aptgent" / "share" / "ViennaRNA" / name)
    for c in candidates:
        if c.is_file():
            return str(c)
    return None


class RNAfoldAdapter:
    """Adapter for ViennaRNA RNAfold."""

    def __init__(self, executable: str = "RNAfold", extra_args: list[str] | None = None, lazy: bool = False) -> None:
        self.executable = executable
        self.extra_args = list(extra_args) if extra_args else ["--noPS", "-d2"]
        self._resolve_param_file()
        if not lazy:
            self._check_binary()

    def _resolve_param_file(self) -> None:
        """Auto-resolve bare parameter file names in ``--paramFile`` args."""
        resolved: list[str] = []
        i = 0
        while i < len(self.extra_args):
            arg = self.extra_args[i]
            if arg == "--paramFile" and i + 1 < len(self.extra_args):
                i += 1
                path = self.extra_args[i]
                if not Path(path).is_file():
                    found = _find_param_file(Path(path).name)
                    if found:
                        path = str(found)
                resolved.extend(["--paramFile", path])
            elif arg.startswith("--paramFile="):
                path = arg.split("=", 1)[1]
                if not Path(path).is_file():
                    found = _find_param_file(Path(path).name)
                    if found:
                        arg = f"--paramFile={found}"
                resolved.append(arg)
            else:
                resolved.append(arg)
            i += 1
        self.extra_args = resolved

    def _check_binary(self) -> None:
        if shutil.which(self.executable) is None:
            raise FileNotFoundError(
                f"{self.executable} not found in PATH. "
                "Please install ViennaRNA (https://www.tbi.univie.ac.at/RNA/)."
            )

    def fold(self, sequence: str, timeout: int = 120) -> SecondaryStructure:
        cmd = [self.executable] + self.extra_args
        try:
            proc = subprocess.run(
                cmd,
                input=sequence + "\n",
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"RNAfold timed out after {timeout}s for sequence of length {len(sequence)}"
            ) from exc
        if proc.returncode != 0:
            raise RuntimeError(f"RNAfold failed: {proc.stderr}")

        lines = [l.strip() for l in proc.stdout.strip().splitlines() if l.strip()]
        if len(lines) < 2:
            raise RuntimeError(f"Unexpected RNAfold output: {proc.stdout}")

        seq_line = lines[0]
        result_line = lines[1]

        # Example: GGGAAACCC (... ) ( -5.60 )
        match = re.search(r"([\.\(\)]+)\s*\(\s*([\-\d\.]+)\s*\)", result_line)
        if not match:
            raise RuntimeError(f"Could not parse RNAfold output: {result_line}")

        dot_bracket = match.group(1).strip()
        mfe = float(match.group(2))

        return SecondaryStructure(
            sequence=seq_line,
            dot_bracket=dot_bracket,
            mfe=mfe,
            features={"mfe": mfe, "length": len(seq_line)},
        )
