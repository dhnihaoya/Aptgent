from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from aptgent.domain.models import CandidateSequence, PredictionResult, TargetMolecule
from aptgent.predictor_runtime.paths import RUNNER_MODULE, default_model_dir


class EnsembleAdapter:
    """Adapter wrapping the internal 9-model ensemble predictor via subprocess.

    Calls the internal predictor runner in its own conda environment so that
    heavy dependencies (rdkit, torch, xgboost, …) need not be installed in
    the main aptgent environment.
    """

    def __init__(
        self,
        model_dir: str | None = None,
        conda_env: str | None = None,
        conda_python: str | None = None,
    ) -> None:
        if model_dir is None:
            model_dir = str(default_model_dir())
        self.model_dir = model_dir
        self.conda_env = conda_env
        self.conda_python = conda_python

        self._project_root = str(Path(__file__).resolve().parents[2])

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_cmd(self) -> list[str]:
        """Return the base command prefix for invoking the predictor CLI."""
        if self.conda_python:
            return [self.conda_python, "-m", RUNNER_MODULE]
        if self.conda_env:
            return [
                "conda", "run",
                "--no-capture-output",
                "-n", self.conda_env,
                "python", "-m", RUNNER_MODULE,
            ]
        return ["python", "-m", RUNNER_MODULE]

    def _run(self, extra_args: list[str], timeout: int = 600) -> subprocess.CompletedProcess[str]:
        """Invoke the predictor CLI with the given extra arguments."""
        cmd = self._build_cmd() + extra_args
        return subprocess.run(
            cmd, capture_output=True, text=True, check=False,
            timeout=timeout, cwd=self._project_root, env=os.environ.copy(),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def predict_batch(
        self,
        candidates: list[CandidateSequence],
        target: TargetMolecule,
    ) -> list[PredictionResult]:
        """Predict for a single target. Returns one PredictionResult per candidate."""
        return self.predict_batch_for_targets(candidates, [target])[
            target.smiles or ""
        ]

    def _predict_batch_via_csv(
        self,
        candidates: list[CandidateSequence],
        target: TargetMolecule,
    ) -> list[PredictionResult]:
        """Run a batch prediction via the CLI batch mode using a temporary CSV."""
        import csv as csv_module

        smiles = target.smiles or ""
        if not smiles:
            raise ValueError("Target molecule must have a resolved SMILES string.")

        # Write temporary input CSV
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, prefix="pred_in_"
        ) as tmp_in:
            writer = csv_module.writer(tmp_in)
            writer.writerow(["sequence", "smiles"])
            for cand in candidates:
                writer.writerow([cand.sequence, smiles])
            in_path = tmp_in.name

        out_path = in_path.replace("pred_in_", "pred_out_").replace(".csv", "_out.csv")

        try:
            proc = self._run(
                [
                    "--model-dir", self.model_dir,
                    "predict",
                    "--input", in_path,
                    "--output", out_path,
                ],
                timeout=600,
            )
            if proc.returncode != 0:
                raise RuntimeError(
                    f"Predictor batch failed (exit {proc.returncode}): "
                    f"{proc.stderr[:500]}"
                )

            results: list[PredictionResult] = []
            with open(out_path, "r", newline="") as f:
                reader = csv_module.DictReader(f)
                for idx, row in enumerate(reader):
                    cand = candidates[idx]
                    cand_id = cand.candidate_id or f"cand_{idx}"
                    individual_raw = row.get("individual", "{}")
                    try:
                        individual = json.loads(individual_raw)
                    except Exception:
                        individual = {}
                    labels = [v["label"] for v in individual.values()]
                    probs = [v["probability"] for v in individual.values()]
                    avg_prob = sum(probs) / len(probs) if probs else 0.0
                    ens_label = 1 if all(l == 1 for l in labels) else 0
                    results.append(
                        PredictionResult(
                            candidate_id=cand_id,
                            model_name="ensemble",
                            target=smiles,
                            score=avg_prob,
                            label=ens_label,
                            probability=avg_prob,
                            raw_outputs={"individual": individual},
                        )
                    )
            return results
        finally:
            for p in (in_path, out_path):
                try:
                    os.unlink(p)
                except Exception:
                    pass

    def predict_batch_for_targets(
        self,
        candidates: list[CandidateSequence],
        targets: list[TargetMolecule],
    ) -> dict[str, list[PredictionResult]]:
        """Predict for multiple targets.

        Returns ``{smiles: [PredictionResult, …]}`` keyed by target SMILES.
        Each PredictionResult includes ensemble score (average probability)
        and per-model details in raw_outputs.
        """
        for t in targets:
            if not t.smiles:
                raise ValueError(
                    "All target molecules must have a resolved SMILES string."
                )

        results_by_target: dict[str, list[PredictionResult]] = {}

        for target in targets:
            results_by_target[target.smiles] = self._predict_batch_via_csv(
                candidates, target
            )

        return results_by_target
