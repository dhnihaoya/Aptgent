"""Model loading and ensemble prediction for the internal predictor runtime."""

from __future__ import annotations

import glob
import os
import pickle
import re
from itertools import product
from typing import Optional

import numpy as np

from aptgent.predictor_runtime.features import (
    _ENCODE_TABLE,
    MER_K_MAP,
    build_feature_matrix,
    build_feature_vector,
    molecular_descriptors,
    rna_to_dna,
)
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
            def forward(self, x):
                if not isinstance(x, torch.Tensor):
                    x = torch.FloatTensor(np.asarray(x, dtype=np.float32))
                if x.dim() == 1:
                    x = x.unsqueeze(0)
                x = x.unsqueeze(0)
                out, _ = self.rnn(x)
                out = out.squeeze(0)
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


class PredictionCancelled(RuntimeError):
    """Raised when an accelerated mutation search is cancelled."""


class EnsemblePredictor:
    """Load all trained models and run strict ensemble prediction."""

    def __init__(self, model_dir: str | os.PathLike[str] | None = None):
        self.model_dir = str(model_dir or default_model_dir())
        self.models: list[tuple[object, str | None, str]] = []
        self._load_all()

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

    @staticmethod
    def _predict_model_batch(model, X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        preds = np.asarray(model.predict(X)).astype(int)
        probs = np.asarray(model.predict_proba(X))[:, 1].astype(float)
        return preds, probs

    def predict_batch(
        self,
        sequences: list[str],
        smiles_list: list[str],
        labels: Optional[list[int]] = None,
        ids: Optional[list[object]] = None,
    ) -> list[dict]:
        """Run the batch predictor and return per-sample ensemble details."""
        all_results: list[dict] = []

        for index, (sequence, smiles) in enumerate(zip(sequences, smiles_list)):
            sample: dict[str, object] = {"sequence": sequence, "smiles": smiles}
            if ids is not None:
                sample["id"] = ids[index]
            if labels is not None:
                sample["true_label"] = labels[index]

            individual: dict[str, dict[str, float | int]] = {}
            model_labels: list[int] = []

            for model, mer, filename in self.models:
                if mer is None or mer not in MER_K_MAP:
                    continue

                features = build_feature_vector(sequence, smiles, MER_K_MAP[mer])
                pred = model.predict(features.reshape(1, -1))[0]
                prob = model.predict_proba(features.reshape(1, -1))[0, 1]
                individual[filename] = {
                    "label": int(pred),
                    "probability": round(float(prob), 6),
                }
                model_labels.append(int(pred))

            sample["individual"] = individual
            sample["ensemble_label"] = 1 if all(label == 1 for label in model_labels) else 0
            all_results.append(sample)

        return all_results

    def predict_mutation_batch(
        self,
        base_sequence: str,
        smiles: str,
        sites: list[int],
        *,
        batch_size: int = 2000,
        sub_batch_size: Optional[int] = None,
        progress_callback=None,
        should_cancel=None,
    ) -> list[dict]:
        """Enumerate and score a mutation space using a vectorized fast path."""
        sequence = rna_to_dna(base_sequence).upper()
        sequence_bytes = np.frombuffer(sequence.encode("ascii"), dtype=np.uint8)
        sequence_chars = list(sequence)
        base_bytes = np.frombuffer(b"ATGC", dtype=np.uint8)
        sites_arr = np.array(sites, dtype=np.intp)

        if np.any(sites_arr < 0) or np.any(sites_arr >= len(sequence)):
            raise ValueError("Mutation site index out of range")

        batch_size = max(1, int(batch_size))
        if sub_batch_size is None:
            sub_batch_size = min(65536, batch_size)
        sub_batch_size = max(1, int(sub_batch_size))
        total = 4 ** len(sites)

        def check_cancelled() -> None:
            if should_cancel and should_cancel():
                raise PredictionCancelled("Mutation search cancelled.")

        check_cancelled()
        descriptors = molecular_descriptors(smiles)

        model_configs: list[tuple[object, str, str, list[int]]] = []
        for model, mer, filename in self.models:
            if mer is None or mer not in MER_K_MAP:
                continue
            model_configs.append((model, mer, filename, MER_K_MAP[mer]))

        calibration_sequences: list[str] = []
        for combo in product(["A", "T", "G", "C"], repeat=len(sites)):
            check_cancelled()
            if len(calibration_sequences) >= 64:
                break
            mutant = sequence_chars.copy()
            for position, new_base in zip(sites, combo):
                mutant[position] = new_base
            calibration_sequences.append("".join(mutant))

        scored_models: list[tuple[int, object, str, str, list[int]]] = []
        for model, mer, filename, k_list in model_configs:
            check_cancelled()
            X = build_feature_matrix(calibration_sequences, descriptors, k_list)
            preds, _ = self._predict_model_batch(model, X)
            scored_models.append((int(preds.sum()), model, mer, filename, k_list))
        scored_models.sort(key=lambda item: item[0])
        ordered_models = [(model, mer, filename, k_list) for _, model, mer, filename, k_list in scored_models]

        positives: list[dict] = []
        processed = 0
        progress_mark = 0

        def flush_chunk(mutant_bytes: np.ndarray) -> None:
            nonlocal processed, progress_mark
            check_cancelled()
            if mutant_bytes.size == 0:
                return

            encoded_mutants = _ENCODE_TABLE[mutant_bytes]
            batch_len = encoded_mutants.shape[0]
            surviving = np.arange(batch_len)
            all_model_probs = np.zeros((batch_len, len(ordered_models)), dtype=np.float64)
            all_model_outputs: list[dict[str, dict[str, float | int]]] = [
                {} for _ in range(batch_len)
            ]

            for model_index, (model, _mer, filename, k_list) in enumerate(ordered_models):
                check_cancelled()
                if len(surviving) == 0:
                    break

                X = build_feature_matrix(encoded_mutants[surviving], descriptors, k_list)
                preds, probs = self._predict_model_batch(model, X)
                all_model_probs[surviving, model_index] = probs

                for candidate_idx, pred, prob in zip(surviving, preds, probs):
                    all_model_outputs[candidate_idx][filename] = {
                        "label": int(pred),
                        "probability": round(float(prob), 6),
                    }

                surviving = surviving[preds >= 0.5]

            processed += batch_len
            progress_mark += batch_len
            if progress_callback and (progress_mark >= batch_size or processed == total):
                progress_callback(processed, total, {})
                progress_mark = 0

            for idx in surviving:
                mean_prob = float(np.mean(all_model_probs[idx]))
                positives.append(
                    {
                        "sequence": mutant_bytes[idx].tobytes().decode("ascii"),
                        "mean_probability": round(mean_prob, 6),
                        "ensemble_label": 1,
                        "individual": all_model_outputs[idx],
                    }
                )

        if len(sites) == 0:
            flush_chunk(sequence_bytes.reshape(1, -1))
        else:
            for start in range(0, total, sub_batch_size):
                check_cancelled()
                stop = min(start + sub_batch_size, total)
                chunk_size = stop - start
                digits = np.empty((chunk_size, len(sites)), dtype=np.int8)
                values = np.arange(start, stop, dtype=np.int64)

                for pos in range(len(sites) - 1, -1, -1):
                    digits[:, pos] = values % 4
                    values //= 4

                mutant_bytes = np.tile(sequence_bytes, (chunk_size, 1))
                mutant_bytes[:, sites_arr] = base_bytes[digits]
                flush_chunk(mutant_bytes)

        positives.sort(key=lambda item: item["mean_probability"], reverse=True)
        return positives
