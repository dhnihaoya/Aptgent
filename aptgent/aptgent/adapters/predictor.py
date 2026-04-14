from __future__ import annotations

import json
import os
import subprocess
import tempfile
from typing import Any

from aptgent.domain.models import CandidateSequence, PredictionResult, TargetMolecule


class EnsembleAdapter:
    """Adapter wrapping the 9-model ensemble predictor via subprocess.

    Calls the ``aptamer-predictor`` CLI in its own conda environment so that
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
            model_dir = os.path.abspath(
                os.path.join(
                    os.path.dirname(__file__),
                    "..", "..", "..", "aptamer_predictor", "models",
                )
            )
        self.model_dir = model_dir
        self.conda_env = conda_env
        self.conda_python = conda_python

        self._cli_path = os.path.abspath(
            os.path.join(
                os.path.dirname(__file__),
                "..", "..", "..", "aptamer_predictor",
            )
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_cmd(self) -> list[str]:
        """Return the base command prefix for invoking the predictor CLI."""
        if self.conda_python:
            return [self.conda_python, "-m", "aptamer_predictor"]
        if self.conda_env:
            return [
                "conda", "run",
                "--no-capture-output",
                "-n", self.conda_env,
                "python", "-m", "aptamer_predictor",
            ]
        return ["python", "-m", "aptamer_predictor"]

    def _run(self, extra_args: list[str], timeout: int = 600) -> subprocess.CompletedProcess[str]:
        """Invoke the predictor CLI with the given extra arguments."""
        cmd = self._build_cmd() + extra_args
        env = os.environ.copy()
        env["PYTHONPATH"] = self._cli_path + (
            os.pathsep + env.get("PYTHONPATH", "")
        )
        return subprocess.run(
            cmd, capture_output=True, text=True, check=False,
            timeout=timeout, env=env,
        )

    def _predict_single(self, seq: str, smiles: str) -> dict[str, Any]:
        """Run a single prediction pair and return parsed JSON.

        The JSON contains ``individual`` (per-model label + probability) and
        ``ensemble_label``, which is exactly what the old in-process adapter
        produced.
        """
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, prefix="pred_",
        ) as tmp:
            tmp_path = tmp.name

        try:
            proc = self._run([
                "--model-dir", self.model_dir,
                "predict",
                "--aptamer", seq,
                "--smiles", smiles,
                "--output", tmp_path,
            ], timeout=300)
            if proc.returncode != 0:
                raise RuntimeError(
                    f"Predictor failed (exit {proc.returncode}): "
                    f"{proc.stderr[:500]}"
                )
            with open(tmp_path) as f:
                return json.load(f)
        finally:
            os.unlink(tmp_path)

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
            smiles = target.smiles
            ensemble_results: list[PredictionResult] = []

            for idx, cand in enumerate(candidates):
                cand_id = cand.candidate_id or f"cand_{idx}"
                result_json = self._predict_single(cand.sequence, smiles)

                individual = result_json.get("individual", {})
                labels = [v["label"] for v in individual.values()]
                probs = [v["probability"] for v in individual.values()]
                avg_prob = sum(probs) / len(probs) if probs else 0.0
                ens_label = 1 if all(l == 1 for l in labels) else 0

                ensemble_results.append(
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

            results_by_target[smiles] = ensemble_results

        return results_by_target
