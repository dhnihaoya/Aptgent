from __future__ import annotations

import json
import subprocess

import pytest

from aptgent.adapters.predictor import EnsembleAdapter
from aptgent.domain.models import TargetMolecule


def test_search_mutation_space_reconstructs_candidates_and_predictions(monkeypatch):
    adapter = EnsembleAdapter(model_dir="/tmp/models")
    payload = {
        "results": [
            {
                "sequence": "AG",
                "mean_probability": 0.85,
                "ensemble_label": 1,
                "individual": {
                    "model_a": {"label": 1, "probability": 0.8},
                    "model_b": {"label": 1, "probability": 0.9},
                },
            }
        ],
        "total_processed": 4,
        "binding_hit_count": 1,
    }

    def fake_run(extra_args, timeout=600):
        assert "mutation-search" in extra_args
        return subprocess.CompletedProcess(
            args=extra_args,
            returncode=0,
            stdout=json.dumps(payload),
            stderr="",
        )

    monkeypatch.setattr(adapter, "_run", fake_run)
    target = TargetMolecule(
        input_text="benzene",
        smiles="C1=CC=CC=C1",
        resolution_status="resolved",
    )

    candidates, predictions, metadata = adapter.search_mutation_space(
        "AA",
        target,
        [1],
        top_k_keep=5,
    )

    assert [candidate.sequence for candidate in candidates] == ["AG"]
    assert candidates[0].mutations[0].position == 1
    assert candidates[0].mutations[0].original == "A"
    assert candidates[0].mutations[0].mutated == "G"
    assert predictions[0].candidate_id == "cand_0"
    assert predictions[0].probability == pytest.approx(0.85)
    assert metadata["total_processed"] == 4
    assert metadata["binding_hit_count"] == 1
