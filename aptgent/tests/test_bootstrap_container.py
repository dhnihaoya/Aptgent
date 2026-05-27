"""Tests for ``aptgent.bootstrap.container``."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aptgent.bootstrap.container import (
    create_engine,
    create_persistence,
    _ensure_model_dir,
    _create_llm_client,
)


# ── create_persistence ──────────────────────────────────────


def test_create_persistence(tmp_path):
    cfg = {"paths": {"runs_dir": str(tmp_path / "runs")}}
    p = create_persistence(cfg)
    assert p.runs_dir == tmp_path / "runs"


def test_create_persistence_default_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = {}
    p = create_persistence(cfg)
    assert p.runs_dir == Path("runs")


# ── create_engine ───────────────────────────────────────────


def test_create_engine():
    mock_persistence = MagicMock()
    engine = create_engine(mock_persistence)
    assert engine.persistence is mock_persistence


# ── _ensure_model_dir ──────────────────────────────────────


def test_ensure_model_dir_fills_default():
    with patch("aptgent.predictor_runtime.paths.default_model_dir", return_value=Path("/default/models")):
        tools = {}
        result = _ensure_model_dir(tools)
        assert result["predictor"]["model_dir"] == "/default/models"


def test_ensure_model_dir_preserves_existing():
    with patch("aptgent.predictor_runtime.paths.default_model_dir") as mock_dm:
        tools = {"predictor": {"model_dir": "/my/custom/dir"}}
        result = _ensure_model_dir(tools)
        assert result["predictor"]["model_dir"] == "/my/custom/dir"
        mock_dm.assert_not_called()


def test_ensure_model_dir_empty_string_fills_default():
    with patch("aptgent.predictor_runtime.paths.default_model_dir", return_value=Path("/default")):
        tools = {"predictor": {"model_dir": ""}}
        result = _ensure_model_dir(tools)
        assert result["predictor"]["model_dir"] == "/default"


# ── _create_llm_client ─────────────────────────────────────


def test_create_llm_client_with_provider():
    with patch("aptgent.llm.client.LLMClient") as MockClient:
        cfg = {"provider": {"openai": {"api_key": "k", "model": "m"}}}
        _create_llm_client(cfg)
        MockClient.assert_called_once_with(config={"api_key": "k", "model": "m"})


def test_create_llm_client_fallback():
    with patch("aptgent.llm.client.LLMClient") as MockClient:
        cfg = {"api_key": "k"}
        _create_llm_client(cfg)
        MockClient.assert_called_once_with(config=cfg)


# ── create_*_adapter factories ──────────────────────────────


def test_create_rna_fold_adapter():
    with patch("aptgent.adapters.rna_fold.RNAfoldAdapter") as MockAdapter:
        from aptgent.bootstrap.container import create_rna_fold_adapter
        create_rna_fold_adapter({"rna_fold": {"command": "RNAfold", "args": "-p"}})
        MockAdapter.assert_called_once_with(
            executable="RNAfold", extra_args="-p", lazy=True,
        )


def test_create_vina_adapter():
    with patch("aptgent.adapters.docking.VinaAdapter") as MockAdapter:
        from aptgent.bootstrap.container import create_vina_adapter
        create_vina_adapter({"docking": {"command": "vina", "exhaustiveness": 16}})
        MockAdapter.assert_called_once_with(
            executable="vina", exhaustiveness=16, num_modes=9,
            energy_range=3.0, lazy=True,
        )


def test_create_prediction_adapter():
    with patch("aptgent.adapters.predictor.EnsembleAdapter") as MockAdapter:
        from aptgent.bootstrap.container import create_prediction_adapter
        create_prediction_adapter({"predictor": {"model_dir": "/m"}})
        MockAdapter.assert_called_once_with(
            model_dir="/m", conda_env=None, conda_python=None,
        )


def test_create_molecule_resolver():
    with patch("aptgent.adapters.molecule.SimpleMoleculeResolver") as MockResolver:
        from aptgent.bootstrap.container import create_molecule_resolver
        create_molecule_resolver()
        MockResolver.assert_called_once()


def test_create_spatial_rank_adapter():
    with patch("aptgent.adapters.spatial_rank.SpatialRankAdapter") as MockAdapter:
        from aptgent.bootstrap.container import create_spatial_rank_adapter
        create_spatial_rank_adapter()
        MockAdapter.assert_called_once()


def test_create_pdb_analysis_adapter():
    with patch("aptgent.adapters.pdb_analysis.PdbAnalysisAdapter") as MockAdapter:
        from aptgent.bootstrap.container import create_pdb_analysis_adapter
        create_pdb_analysis_adapter({"pdb_analysis": {"command": "wget"}})
        MockAdapter.assert_called_once_with(
            wget_command="wget",
            base_url="https://files.rcsb.org/download",
        )


def test_create_receptor_prep_adapter():
    with patch("aptgent.adapters.receptor_prep.ReceptorPreparationAdapter") as MockAdapter:
        from aptgent.bootstrap.container import create_receptor_prep_adapter
        create_receptor_prep_adapter({"receptor_prep": {"obabel": "obabel", "padding_angstrom": "5.0"}})
        MockAdapter.assert_called_once_with(
            obabel_command="obabel", default_padding=5.0,
        )


def test_create_rnacomposer_adapter():
    with patch("aptgent.adapters.rnacomposer.RNAComposerAdapter") as MockAdapter:
        from aptgent.bootstrap.container import create_rnacomposer_adapter
        create_rnacomposer_adapter({"rnacomposer": {"timeout_seconds": "120"}})
        MockAdapter.assert_called_once_with(
            base_url="https://rnacomposer.cs.put.poznan.pl",
            timeout_seconds=120,
            max_poll_seconds=1800,
            poll_interval_seconds=15,
        )
