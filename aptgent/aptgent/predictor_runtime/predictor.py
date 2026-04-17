"""Model loading and ensemble prediction for the internal predictor runtime."""

from __future__ import annotations

import glob
import os
import pickle
import re
from typing import Optional

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
