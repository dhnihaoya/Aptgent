"""Lightweight path helpers shared by the predictor adapter and runtime."""

from __future__ import annotations

from pathlib import Path

RUNNER_MODULE = "aptgent.predictor_runtime.runner"


def default_model_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "resources" / "predictor_models"
