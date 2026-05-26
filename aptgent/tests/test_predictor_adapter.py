from __future__ import annotations

import sys
from pathlib import Path

from aptgent.adapters.predictor import EnsembleAdapter
from aptgent.predictor_runtime.paths import RUNNER_MODULE


def test_prediction_adapter_uses_internal_runner_module():
    adapter = EnsembleAdapter(model_dir="/tmp/models")

    assert adapter._build_cmd() == [
        sys.executable,
        "-m",
        RUNNER_MODULE,
    ]


def test_prediction_runtime_module_lives_outside_adapters_package():
    assert RUNNER_MODULE == "aptgent.predictor_runtime.runner"


def test_prediction_adapter_defaults_model_dir_to_internal_resources():
    adapter = EnsembleAdapter()

    model_dir = Path(adapter.model_dir)
    assert model_dir.name == "predictor_models"
    assert model_dir.parts[-3:] == ("aptgent", "resources", "predictor_models")
