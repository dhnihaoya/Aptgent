from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable

from aptgent.domain.models import CandidateSequence, PredictionResult, TargetMolecule
from aptgent.predictor_runtime.paths import RUNNER_MODULE, default_model_dir

_log = logging.getLogger(__name__)


class EnsembleAdapter:
    """Adapter wrapping the internal 9-model ensemble predictor via subprocess.

    In the default single-environment setup all dependencies live in the
    same conda env and ``conda_env`` / ``conda_python`` are left empty,
    so the predictor runs under ``sys.executable`` directly.  Set these
    fields only when the predictor runtime is isolated in a separate env.
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
        self.conda_env = conda_env or None
        self.conda_python = conda_python or None

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
        import sys
        return [sys.executable, "-m", RUNNER_MODULE]

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
        """Run a batch prediction via the CLI batch mode using a temporary CSV.

        Rows are matched back to candidates via an explicit ``candidate_id``
        column rather than by row order, because the predictor runtime is
        allowed to skip empty/malformed rows and preserving alignment by index
        alone would silently corrupt results.
        """
        import csv as csv_module

        smiles = target.smiles or ""
        if not smiles:
            raise ValueError("Target molecule must have a resolved SMILES string.")

        cand_by_id: dict[str, CandidateSequence] = {}
        for idx, cand in enumerate(candidates):
            cid = cand.candidate_id or f"cand_{idx}"
            cand_by_id[cid] = cand

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, prefix="pred_in_"
        ) as tmp_in:
            writer = csv_module.writer(tmp_in)
            writer.writerow(["candidate_id", "sequence", "smiles"])
            for idx, cand in enumerate(candidates):
                cid = cand.candidate_id or f"cand_{idx}"
                writer.writerow([cid, cand.sequence, smiles])
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

            results_by_id: dict[str, PredictionResult] = {}
            with open(out_path, "r", newline="") as f:
                reader = csv_module.DictReader(f)
                for row in reader:
                    cid = (row.get("candidate_id") or "").strip()
                    if not cid or cid not in cand_by_id:
                        continue
                    individual_raw = row.get("individual", "{}")
                    try:
                        individual = json.loads(individual_raw)
                    except json.JSONDecodeError:
                        individual = {}
                    labels = [v.get("label", 0) for v in individual.values()]
                    probs = [v.get("probability", 0.0) for v in individual.values()]
                    avg_prob = sum(probs) / len(probs) if probs else 0.0
                    ens_label = 1 if labels and all(l == 1 for l in labels) else 0
                    results_by_id[cid] = PredictionResult(
                        candidate_id=cid,
                        model_name="ensemble",
                        target=smiles,
                        score=avg_prob,
                        label=ens_label,
                        probability=avg_prob,
                        raw_outputs={"individual": individual},
                    )

            results: list[PredictionResult] = []
            for idx, cand in enumerate(candidates):
                cid = cand.candidate_id or f"cand_{idx}"
                if cid in results_by_id:
                    results.append(results_by_id[cid])
                else:
                    results.append(
                        PredictionResult(
                            candidate_id=cid,
                            model_name="ensemble",
                            target=smiles,
                            score=0.0,
                            label=0,
                            probability=0.0,
                            raw_outputs={"individual": {}, "error": "missing_row"},
                        )
                    )
            return results
        finally:
            for p in (in_path, out_path):
                try:
                    os.unlink(p)
                except OSError:
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

    def predict_mutation_batch(
        self,
        base_sequence: str,
        target: TargetMolecule,
        sites: list[int],
        *,
        progress_callback: Callable[[int, int, dict], None] | None = None,
        result_callback: Callable[[dict], None] | None = None,
        progress_every: int = 10000,
        cancel_event: threading.Event | None = None,
        timeout_seconds: int | None = 3600,
        skip_first: int = 0,
        batch_size: int | None = None,
    ) -> dict[str, Any]:
        """Run mutation-batch via subprocess with line-JSON protocol.

        Streams positives-only hits through ``result_callback``.
        Returns summary dict with total, hits, device, model_order.

        The subprocess lifecycle is guarded by:

        * a dedicated stderr-pump thread (stderr is ``PIPE``-backed and the OS
          pipe buffer would otherwise block the child once full);
        * a total wall-clock watchdog (``timeout_seconds``) that triggers the
          same three-stage termination as a cooperative cancel
          (``cancel\\n`` on stdin -> ``terminate()`` -> ``kill()``).
        """
        smiles = target.smiles or ""
        if not smiles:
            raise ValueError("Target molecule must have a resolved SMILES string.")

        effective_progress_every = progress_every
        if batch_size is not None:
            effective_progress_every = batch_size

        sites_str = ",".join(str(s) for s in sites)
        cmd = self._build_cmd() + [
            "--model-dir", self.model_dir,
            "mutation-batch",
            "--base-sequence", base_sequence,
            "--smiles", smiles,
            "--sites", sites_str,
            "--progress-every", str(int(effective_progress_every)),
        ]
        if skip_first > 0:
            cmd.extend(["--skip-first", str(skip_first)])

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE,
            bufsize=1,
            text=True,
            cwd=self._project_root,
            env=os.environ.copy(),
        )

        summary: dict[str, Any] = {"total": 0, "hits": 0}
        stderr_chunks: list[str] = []
        subprocess_error: dict[str, Any] = {}

        def _reader() -> None:
            try:
                for line in proc.stdout:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    msg_type = obj.get("type")
                    if msg_type == "progress" and progress_callback:
                        progress_callback(obj["done"], obj["total"], {})
                    elif msg_type == "hit" and result_callback:
                        result_callback({
                            "sequence": obj["sequence"],
                            "ensemble_label": 1,
                            "probability": obj["mean_probability"],
                            "model_probabilities": obj.get("model_probabilities", []),
                        })
                    elif msg_type == "done":
                        summary["total"] = obj.get("total", 0)
                        summary["hits"] = obj.get("hits", 0)
                        if "device" in obj:
                            summary["device"] = obj["device"]
                        if "model_order" in obj:
                            summary["model_order"] = obj["model_order"]
                        if obj.get("cancelled"):
                            summary["cancelled"] = True
                    elif msg_type == "ready":
                        summary["device"] = obj.get("device", "cpu")
                        summary["model_order"] = obj.get("model_order", [])
                    elif msg_type == "error":
                        subprocess_error["message"] = obj.get("message", "")
            except Exception as exc:
                _log.debug("mutation-batch stdout reader aborted: %s", exc)

        def _stderr_pump() -> None:
            try:
                for line in proc.stderr:
                    stderr_chunks.append(line)
            except Exception as exc:
                _log.debug("mutation-batch stderr pump aborted: %s", exc)

        reader_thread = threading.Thread(target=_reader, daemon=True)
        stderr_thread = threading.Thread(target=_stderr_pump, daemon=True)
        reader_thread.start()
        stderr_thread.start()

        timed_out = False
        start = time.monotonic()

        def _send_cancel() -> None:
            try:
                if proc.stdin and not proc.stdin.closed:
                    proc.stdin.write("cancel\n")
                    proc.stdin.flush()
            except (OSError, ValueError):
                pass

        try:
            while reader_thread.is_alive():
                reader_thread.join(timeout=0.5)
                if cancel_event is not None and cancel_event.is_set():
                    _send_cancel()
                    break
                if timeout_seconds is not None and (time.monotonic() - start) > timeout_seconds:
                    timed_out = True
                    _log.warning(
                        "mutation-batch subprocess exceeded %ss; requesting cancel.",
                        timeout_seconds,
                    )
                    _send_cancel()
                    break
        finally:
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                _log.warning("mutation-batch subprocess did not exit; terminating.")
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    _log.warning("mutation-batch subprocess still alive; killing.")
                    proc.kill()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        pass
            reader_thread.join(timeout=5)
            stderr_thread.join(timeout=5)
            try:
                if proc.stdout:
                    proc.stdout.close()
                if proc.stderr:
                    proc.stderr.close()
                if proc.stdin:
                    proc.stdin.close()
            except OSError:
                pass

        stderr_output = "".join(stderr_chunks)
        if timed_out:
            summary["cancelled"] = True
            summary["timed_out"] = True
        if cancel_event is not None and cancel_event.is_set():
            summary["cancelled"] = True

        if subprocess_error:
            raise RuntimeError(
                "Predictor mutation-batch reported error: "
                f"{subprocess_error.get('message', '')[:500]}"
            )

        rc = proc.returncode
        # rc == 0 success; rc == 1 is a cooperative cancel (PredictionCancelled)
        if rc not in (0, 1):
            raise RuntimeError(
                f"Predictor mutation-batch failed (exit {rc}): "
                f"{stderr_output[:500]}"
            )

        return summary
