from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable

from aptgent.domain.models import CandidateSequence, PredictionResult, TargetMolecule
from aptgent.predictor_runtime.paths import RUNNER_MODULE, default_model_dir
from aptgent.protocol.subprocess_stream import SubprocessSession


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

    def _run_streaming_subprocess(
        self,
        cmd: list[str],
        *,
        on_line: Callable[[dict], None],
        cancel_event: threading.Event | None,
        timeout_seconds: int | None,
    ) -> tuple[int, str, bool]:
        """Spawn a streaming predictor subprocess and dispatch JSON lines.

        Delegates to :class:`SubprocessSession` for process lifecycle
        management.  Returns ``(returncode, stderr_output, timed_out)``.
        Raises :class:`RuntimeError` on subprocess-reported errors.
        """
        session = SubprocessSession(cmd, env=os.environ.copy(), cwd=self._project_root)
        return session.run(on_line=on_line, cancel_event=cancel_event, timeout_seconds=timeout_seconds)

    def predict_specificity_batch(
        self,
        candidates: list[CandidateSequence],
        targets: list[TargetMolecule],
        *,
        progress_callback: Callable[[int, int, dict], None] | None = None,
        row_callback: Callable[[dict], None] | None = None,
        cancel_event: threading.Event | None = None,
        timeout_seconds: int | None = 3600,
        progress_every: int = 1,
        skip_pairs: list[tuple[int, str]] | None = None,
    ) -> dict[str, Any]:
        """Run streaming specificity cross-prediction via the predictor CLI.

        Streams events through ``progress_callback(done, total, extra)`` and
        ``row_callback({target_idx, target_name, candidate_id, label, probability})``.
        Returns a summary dict with ``total``, ``device``, ``model_order``, and
        optionally ``cancelled`` when the subprocess exits cooperatively.

        ``skip_pairs`` is an optional list of ``(target_idx, candidate_id)``
        tuples that the subprocess should skip; the caller (the job runner)
        uses this to resume after a partial run.
        """
        for target in targets:
            if not target.smiles:
                raise ValueError(
                    "All target molecules must have a resolved SMILES string."
                )

        candidates_payload = [
            {
                "candidate_id": c.candidate_id or f"cand_{idx}",
                "sequence": c.sequence,
            }
            for idx, c in enumerate(candidates)
        ]
        targets_payload = [
            {
                "name": (t.resolved_name or t.input_text or ""),
                "smiles": t.smiles or "",
            }
            for t in targets
        ]

        cleanup_paths: list[str] = []
        skip_file_path: str | None = None
        try:
            cand_file = tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False, prefix="spec_cands_"
            )
            cleanup_paths.append(cand_file.name)
            json.dump(candidates_payload, cand_file)
            cand_file.flush()
            cand_file.close()

            tgt_file = tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False, prefix="spec_tgts_"
            )
            cleanup_paths.append(tgt_file.name)
            json.dump(targets_payload, tgt_file)
            tgt_file.flush()
            tgt_file.close()

            cmd = self._build_cmd() + [
                "--model-dir", self.model_dir,
                "specificity-batch",
                "--candidates-json", cand_file.name,
                "--targets-json", tgt_file.name,
                "--progress-every", str(int(progress_every)),
            ]
            if skip_pairs:
                skip_file = tempfile.NamedTemporaryFile(
                    mode="w", suffix=".json", delete=False, prefix="spec_skip_"
                )
                json.dump(
                    [[int(idx), str(cid)] for idx, cid in skip_pairs],
                    skip_file,
                )
                skip_file.flush()
                skip_file.close()
                skip_file_path = skip_file.name
                cmd.extend(["--skip-pairs-json", skip_file_path])

            summary: dict[str, Any] = {"total": len(candidates) * len(targets)}

            def _on_line(obj: dict) -> None:
                msg_type = obj.get("type")
                if msg_type == "ready":
                    summary["device"] = obj.get("device", "cpu")
                    summary["model_order"] = obj.get("model_order", [])
                    if "total" in obj:
                        summary["total"] = obj["total"]
                elif msg_type == "progress" and progress_callback:
                    extra = {
                        k: obj[k]
                        for k in ("target_idx", "target_name")
                        if k in obj
                    }
                    progress_callback(
                        int(obj.get("done", 0)),
                        int(obj.get("total", summary["total"])),
                        extra,
                    )
                elif msg_type == "row" and row_callback:
                    row_callback({
                        "target_idx": int(obj.get("target_idx", 0)),
                        "target_name": str(obj.get("target_name", "")),
                        "candidate_id": str(obj.get("candidate_id", "")),
                        "label": int(obj.get("label", 0)),
                        "probability": float(obj.get("probability", 0.0)),
                    })
                elif msg_type == "done":
                    if obj.get("cancelled"):
                        summary["cancelled"] = True
                    if "total" in obj:
                        summary["total"] = obj["total"]

            rc, stderr_output, _timed_out = self._run_streaming_subprocess(
                cmd,
                on_line=_on_line,
                cancel_event=cancel_event,
                timeout_seconds=timeout_seconds,
            )

            if cancel_event is not None and cancel_event.is_set():
                summary["cancelled"] = True

            # rc == 0 success; rc == 1 is a cooperative cancel
            if rc not in (0, 1):
                raise RuntimeError(
                    f"Predictor specificity-batch failed (exit {rc}): "
                    f"{stderr_output[:500]}"
                )

            return summary
        finally:
            for path in cleanup_paths:
                try:
                    os.unlink(path)
                except OSError:
                    pass
            if skip_file_path is not None:
                try:
                    os.unlink(skip_file_path)
                except OSError:
                    pass

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
        sub_batch_size: int | None = None,
    ) -> dict[str, Any]:
        """Run mutation-batch via subprocess with line-JSON protocol.

        Streams positives-only hits through ``result_callback``.
        Returns summary dict with total, hits, device, model_order.
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
        if sub_batch_size is not None:
            cmd.extend(["--sub-batch-size", str(sub_batch_size)])
        if skip_first > 0:
            cmd.extend(["--skip-first", str(skip_first)])

        summary: dict[str, Any] = {"total": 0, "hits": 0}

        def _on_line(obj: dict) -> None:
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

        rc, stderr_output, timed_out = self._run_streaming_subprocess(
            cmd,
            on_line=_on_line,
            cancel_event=cancel_event,
            timeout_seconds=timeout_seconds,
        )

        if timed_out:
            summary["cancelled"] = True
            summary["timed_out"] = True
        if cancel_event is not None and cancel_event.is_set():
            summary["cancelled"] = True

        # rc == 0 success; rc == 1 is a cooperative cancel (PredictionCancelled)
        if rc not in (0, 1):
            raise RuntimeError(
                f"Predictor mutation-batch failed (exit {rc}): "
                f"{stderr_output[:500]}"
            )

        return summary
