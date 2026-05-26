"""Model loading and ensemble prediction for the internal predictor runtime."""

from __future__ import annotations

import glob
import os
import pickle
import re
from typing import Callable, Optional

import numpy as np

from aptgent.predictor_runtime.features import MER_K_MAP, build_feature_vector
from aptgent.predictor_runtime.paths import default_model_dir

_TORCH_AVAILABLE = False
_nn = None


def _ensure_torch():
    global _TORCH_AVAILABLE, _nn
    if _nn is None:
        try:
            import torch
            import torch.nn as nn

            _nn = nn
            _TORCH_AVAILABLE = True
        except ImportError as exc:
            raise ImportError(
                "PyTorch is required for loading RNN/biRNN models. "
                "Install it in the predictor runtime environment."
            ) from exc


class SimpleRNN:
    """PyTorch wrapper compatible with the serialized sklearn-like interface."""

    _nn_module = None

    @classmethod
    def _as_module(cls):
        if cls._nn_module is not None:
            return cls._nn_module

        _ensure_torch()
        import torch
        import torch.nn as nn

        class _SimpleRNN(nn.Module):
            def _to_device(self, x):
                device = next(self.parameters()).device
                if not isinstance(x, torch.Tensor):
                    x = torch.tensor(
                        np.asarray(x, dtype=np.float32), device=device
                    )
                elif x.device != device:
                    x = x.to(device)
                return x

            def forward(self, x):
                x = self._to_device(x)
                if x.dim() == 1:
                    x = x.unsqueeze(0)
                x = x.unsqueeze(1)
                out, _ = self.rnn(x)
                out = out.squeeze(1)
                out = self.sig1(self.fc1(out))
                out = self.sig2(self.fc2(out))
                return out.squeeze(-1)

            def predict_proba(self, X):
                self.eval()
                with torch.no_grad():
                    if not isinstance(X, np.ndarray):
                        X = np.asarray(X, dtype=np.float32)
                    tensor = torch.FloatTensor(X)
                    if tensor.dim() == 1:
                        tensor = tensor.unsqueeze(0)
                    out = self.forward(tensor).cpu().numpy()
                    return np.column_stack([1 - out, out])

            def predict(self, X):
                probs = self.predict_proba(X)
                return (probs[:, 1] >= 0.5).astype(int)

        cls._nn_module = _SimpleRNN
        return _SimpleRNN


class PredictionCancelled(Exception):
    """Raised when a long-running mutation search is cancelled."""


def _extract_mer_label(filename: str) -> Optional[str]:
    match = re.search(r"\((\d+mer)\)", filename)
    return match.group(1) if match else None


def load_model(filepath: str):
    """Load a single serialized model, handling PyTorch pickles when needed."""
    mer = _extract_mer_label(os.path.basename(filepath))
    basename = os.path.basename(filepath)
    is_pytorch = basename.endswith("RNN.pkl") or basename.endswith("biRNN.pkl")

    if is_pytorch:
        _ensure_torch()
        import __main__

        __main__.SimpleRNN = SimpleRNN._as_module()

    with open(filepath, "rb") as handle:
        model = pickle.load(handle)

    return model, mer


class EnsemblePredictor:
    """Load all trained models and run strict ensemble prediction."""

    def __init__(self, model_dir: str | os.PathLike[str] | None = None):
        self.model_dir = str(model_dir or default_model_dir())
        self.models: list[tuple[object, str | None, str]] = []
        self._device: str = "cpu"
        self._load_all()
        self._setup_cuda()

    def _load_all(self) -> None:
        pattern = os.path.join(self.model_dir, "(*mer)*.pkl")
        files = sorted(glob.glob(pattern))
        if not files:
            files = sorted(glob.glob(os.path.join(self.model_dir, "*.pkl")))
        if not files:
            raise FileNotFoundError(f"No .pkl model files found in {self.model_dir}")

        for filepath in files:
            model, mer = load_model(filepath)
            self.models.append((model, mer, os.path.basename(filepath)))

    def _setup_cuda(self) -> None:
        from aptgent.predictor_runtime.cuda import get_device

        self._device = get_device()
        if self._device != "cuda":
            return

        import torch

        new_models = []
        for model, mer, fname in self.models:
            if isinstance(model, torch.nn.Module):
                model = model.to("cuda")
            new_models.append((model, mer, fname))
        self.models = new_models

    @staticmethod
    def _is_xgboost(model) -> bool:
        try:
            from xgboost import Booster, XGBClassifier

            return isinstance(model, (XGBClassifier, Booster))
        except ImportError:
            return False

    def _predict_batch(self, model, X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Batch prediction with optional CUDA acceleration.

        Returns (predictions, positive_class_probabilities).
        """
        if self._device == "cuda" and self._is_xgboost(model):
            try:
                import xgboost as xgb

                booster = model.get_booster()
                dm = xgb.DMatrix(X.astype(np.float32), device="cuda")
                probs = booster.predict(dm)
                return (probs >= 0.5).astype(int), probs
            except Exception:
                pass

        preds = model.predict(X)
        probs = model.predict_proba(X)[:, 1]
        return preds.astype(int), probs

    def predict_batch(
        self,
        sequences: list[str],
        smiles_list: list[str],
        labels: Optional[list[int]] = None,
        ids: Optional[list[object]] = None,
        *,
        row_callback: Optional[Callable[[dict], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> list[dict]:
        """Run the batch predictor and return per-sample ensemble details.

        ``row_callback``, when set, is invoked with each finalized sample dict
        as rows complete; cooperators (e.g. the streaming CLI) use this to
        emit progress events without waiting for the full batch.

        ``should_cancel`` is checked between rows; if it returns ``True``,
        :class:`PredictionCancelled` is raised so the caller can finalize the
        partial result set.
        """
        all_results: list[dict] = []

        for index, (sequence, smiles) in enumerate(zip(sequences, smiles_list)):
            if should_cancel and should_cancel():
                raise PredictionCancelled()
            sample: dict[str, object] = {"sequence": sequence, "smiles": smiles}
            if ids is not None:
                sample["id"] = ids[index]
            if labels is not None:
                sample["true_label"] = labels[index]

            individual: dict[str, dict[str, float | int]] = {}
            model_labels: list[int] = []
            model_probs: list[float] = []

            for model, mer, filename in self.models:
                if mer is None or mer not in MER_K_MAP:
                    continue

                features = build_feature_vector(sequence, smiles, MER_K_MAP[mer])
                # Route through ``_predict_batch`` so XGBoost models can use
                # the CUDA DMatrix fast path when a GPU is available.
                preds, probs = self._predict_batch(
                    model, features.reshape(1, -1)
                )
                pred = int(preds[0])
                prob = float(probs[0])
                individual[filename] = {
                    "label": pred,
                    "probability": round(prob, 6),
                }
                model_labels.append(pred)
                model_probs.append(prob)

            sample["individual"] = individual
            if not model_labels:
                sample["ensemble_label"] = 0
                sample["mean_probability"] = 0.0
            else:
                sample["ensemble_label"] = (
                    1 if all(label == 1 for label in model_labels) else 0
                )
                sample["mean_probability"] = round(
                    sum(model_probs) / len(model_probs), 6
                )
            all_results.append(sample)
            if row_callback:
                row_callback(sample)

        return all_results

    def predict_mutation_batch(
        self,
        base_sequence: str,
        smiles: str,
        sites: list[int],
        *,
        batch_size: int = 2000,
        sub_batch_size: Optional[int] = None,
        progress_callback: Optional[Callable] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
        result_callback: Optional[Callable[[dict], None]] = None,
        collect_results: bool = True,
        skip_first: int = 0,
    ) -> Optional[list[dict]]:
        """Enumerate all mutants at selected sites, batch-predict with cascade filtering.

        Collects **only** candidates where all 9 models predict binding
        (ensemble_label == 1).

        If *skip_first* > 0, the first *skip_first* candidates in the
        enumeration order are skipped (used for resume after partial run).
        """
        from itertools import product as itertools_product

        from aptgent.predictor_runtime.features import (
            _ENCODE_TABLE,
            build_feature_matrix,
            molecular_descriptors,
            rna_to_dna,
        )

        seq = rna_to_dna(base_sequence).upper()
        seq_list = list(seq)
        seq_bytes = np.frombuffer(seq.encode("ascii"), dtype=np.uint8)
        bases = ["A", "T", "G", "C"]
        base_bytes = np.frombuffer(b"ATGC", dtype=np.uint8)
        sites_arr = np.array(sites, dtype=np.intp)
        if np.any(sites_arr < 0) or np.any(sites_arr >= len(seq)):
            raise ValueError("Mutation site index out of range")

        batch_size = max(1, int(batch_size))
        if sub_batch_size is None:
            sub_batch_size = min(65536, batch_size)
        sub_batch_size = max(1, int(sub_batch_size))
        total = 4 ** len(sites)

        def _check_cancelled() -> None:
            if should_cancel and should_cancel():
                raise PredictionCancelled()

        # Pre-compute molecular descriptors once
        _check_cancelled()
        desc = molecular_descriptors(smiles)

        # Collect per-model configs
        model_configs = []
        for model, mer, fname in self.models:
            if mer is None or mer not in MER_K_MAP:
                continue
            model_configs.append((model, mer, fname, MER_K_MAP[mer]))

        # Calibrate: determine optimal model order via small sample
        calib_seqs = []
        for combo in itertools_product(bases, repeat=len(sites)):
            _check_cancelled()
            if len(calib_seqs) >= 64:
                break
            mutant = seq_list.copy()
            for pos, new_base in zip(sites, combo):
                if 0 <= pos < len(mutant):
                    mutant[pos] = new_base
            calib_seqs.append("".join(mutant))

        scored: list[tuple[int, object, str, str, list[int]]] = []
        for model, mer, fname, k_list in model_configs:
            _check_cancelled()
            X = build_feature_matrix(calib_seqs, desc, k_list)
            preds, _ = self._predict_batch(model, X)
            n_pos = int(preds.sum())
            scored.append((n_pos, model, mer, fname, k_list))
        scored.sort(key=lambda x: x[0])

        ordered_models = [(m, mer, fn, kl) for _, m, mer, fn, kl in scored]

        # Main enumeration with early-exit filtering
        positives: Optional[list[dict]] = [] if collect_results else None
        done = skip_first
        progress_mark = 0

        def _flush_chunk(mutant_bytes: np.ndarray) -> None:
            nonlocal done, progress_mark
            _check_cancelled()
            if mutant_bytes.size == 0:
                return

            encoded_mutants = _ENCODE_TABLE[mutant_bytes]
            B = encoded_mutants.shape[0]

            surviving = np.arange(B)
            all_model_probs = np.zeros((B, len(ordered_models)), dtype=np.float64)

            for m_idx, (model, mer, fname, k_list) in enumerate(ordered_models):
                _check_cancelled()
                if len(surviving) == 0:
                    break

                X = build_feature_matrix(encoded_mutants[surviving], desc, k_list)
                preds, probs = self._predict_batch(model, X)

                all_model_probs[surviving, m_idx] = probs

                mask = preds >= 0.5
                surviving = surviving[mask]

            done += B
            progress_mark += B
            if progress_callback and (progress_mark >= batch_size or done == total):
                _check_cancelled()
                progress_callback(done, total, {})
                progress_mark = 0

            for idx in surviving:
                probs = all_model_probs[idx]
                mean_prob = float(np.mean(probs))
                result = {
                    "sequence": mutant_bytes[idx].tobytes().decode("ascii"),
                    "mean_probability": round(mean_prob, 6),
                    "ensemble_label": 1,
                    "model_probabilities": [round(float(p), 6) for p in probs],
                }
                if result_callback:
                    result_callback(result)
                if positives is not None:
                    positives.append(result)

        if len(sites) == 0:
            if skip_first == 0:
                _flush_chunk(seq_bytes.reshape(1, -1))
        else:
            enum_start = (skip_first // sub_batch_size) * sub_batch_size
            for start in range(enum_start, total, sub_batch_size):
                _check_cancelled()
                stop = min(start + sub_batch_size, total)

                actual_start = max(start, skip_first)
                if actual_start >= stop:
                    continue
                batch_len = stop - actual_start

                digits = np.empty((batch_len, len(sites)), dtype=np.int8)
                values = np.arange(actual_start, stop, dtype=np.int64)

                for pos in range(len(sites) - 1, -1, -1):
                    digits[:, pos] = values % 4
                    values //= 4

                mutant_bytes = np.tile(seq_bytes, (batch_len, 1))
                mutant_bytes[:, sites_arr] = base_bytes[digits]
                _flush_chunk(mutant_bytes)

        if positives is None:
            return None

        positives.sort(key=lambda r: r["mean_probability"], reverse=True)
        return positives
