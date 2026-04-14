from __future__ import annotations

import re
import shutil
import subprocess

from aptgent.domain.models import SecondaryStructure


class RNAfoldAdapter:
    """Adapter for ViennaRNA RNAfold."""

    def __init__(self, executable: str = "RNAfold", extra_args: list[str] | None = None, lazy: bool = False) -> None:
        self.executable = executable
        self.extra_args = extra_args or ["--noPS", "-d2"]
        if not lazy:
            self._check_binary()

    def _check_binary(self) -> None:
        if shutil.which(self.executable) is None:
            raise FileNotFoundError(
                f"{self.executable} not found in PATH. "
                "Please install ViennaRNA (https://www.tbi.univie.ac.at/RNA/)."
            )

    def fold(self, sequence: str) -> SecondaryStructure:
        cmd = [self.executable] + self.extra_args
        proc = subprocess.run(
            cmd,
            input=sequence + "\n",
            capture_output=True,
            text=True,
            check=False,
        )
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
