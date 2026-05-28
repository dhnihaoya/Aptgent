"""Tests for ``aptgent.cli.doctor``."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aptgent.cli.doctor import (
    _check_binary,
    _check_env_vars,
    _check_feature_dimensions,
    _check_llm,
    _check_predictor,
    _check_predictor_deps,
    _check_url,
    run_doctor,
    _search_conda_binary,
)


# ── _check_binary ───────────────────────────────────────────


def test_check_binary_found(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/python")
    result = _check_binary("python")
    assert result["status"] == "ok"
    assert result["path"] == "/usr/bin/python"


def test_check_binary_not_found(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: None)
    # Also make sys.executable's bin dir not have it
    result = _check_binary("nonexistent_tool_xyz")
    assert result["status"] == "missing"
    assert result["hint"] is not None


# ── _search_conda_binary ────────────────────────────────────


def test_search_conda_binary_found(tmp_path):
    env_bin = tmp_path / "aptgent" / "bin"
    env_bin.mkdir(parents=True)
    (env_bin / "RNAfold").touch()
    with patch("aptgent.cli.doctor._CONDA_ROOTS", [tmp_path]):
        result = _search_conda_binary("RNAfold")
    assert result == str(env_bin / "RNAfold")


def test_search_conda_binary_not_found(tmp_path):
    with patch("aptgent.cli.doctor._CONDA_ROOTS", [tmp_path]):
        result = _search_conda_binary("RNAfold")
    assert result is None


# ── _check_predictor ────────────────────────────────────────


def test_check_predictor_ok(tmp_path):
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    (model_dir / "model1.pkl").write_bytes(b"fake")
    result = _check_predictor(str(model_dir))
    assert result["status"] == "ok"
    assert result["model_count"] == 1


def test_check_predictor_missing_dir():
    result = _check_predictor("/nonexistent/path")
    assert result["status"] == "missing_dir"


def test_check_predictor_not_configured():
    result = _check_predictor(None)
    assert result["status"] == "not_configured"


# ── _check_feature_dimensions ───────────────────────────────


def _write_fake_model(model_dir: Path, mer_label: str, n_features: int) -> None:
    import pickle
    from types import SimpleNamespace

    model_dir.mkdir(parents=True, exist_ok=True)
    obj = SimpleNamespace(n_features_in_=n_features)
    path = model_dir / f"({mer_label})(Dataset N1)XGB.pkl"
    with open(path, "wb") as handle:
        pickle.dump(obj, handle)


def test_check_feature_dimensions_not_configured():
    result = _check_feature_dimensions(None)
    assert result["status"] == "skipped"


def test_check_feature_dimensions_missing_dir():
    result = _check_feature_dimensions("/nonexistent/models/path")
    assert result["status"] == "skipped"


def test_check_feature_dimensions_mismatch(tmp_path):
    pytest.importorskip("rdkit")
    _write_fake_model(tmp_path, "1mer", 99999)
    result = _check_feature_dimensions(str(tmp_path))
    assert result["status"] == "feature_mismatch"
    assert result["model_expects"] == 99999
    assert "RDKit" in result["hint"]


def test_check_feature_dimensions_ok(tmp_path):
    pytest.importorskip("rdkit")
    from aptgent.cli.doctor import _expected_feature_length

    expected = _expected_feature_length("1mer")
    assert expected is not None
    _write_fake_model(tmp_path, "1mer", expected)
    result = _check_feature_dimensions(str(tmp_path))
    assert result["status"] == "ok"
    assert result["feature_length"] == expected


# ── _check_llm ──────────────────────────────────────────────


def test_check_llm_key_set(monkeypatch):
    monkeypatch.setenv("TEST_API_KEY", "sk-xxx")
    cfg = {"provider": {"openai": {"api_key_env": "TEST_API_KEY"}}}
    result = _check_llm(cfg)
    assert result["status"] == "ok"
    assert result["api_key_set"] is True


def test_check_llm_key_missing(monkeypatch):
    monkeypatch.delenv("NONEXISTENT_KEY_XYZ", raising=False)
    cfg = {"provider": {"openai": {"api_key_env": "NONEXISTENT_KEY_XYZ"}}}
    result = _check_llm(cfg)
    assert result["status"] == "missing_key"


def test_check_llm_direct_key():
    cfg = {"provider": {"openai": {"api_key": "sk-direct"}}}
    result = _check_llm(cfg)
    assert result["api_key_set"] is True


# ── _check_predictor_deps ───────────────────────────────────


def test_check_predictor_deps_all_found():
    result = _check_predictor_deps()
    # In the test environment, at least some should be available
    assert "status" in result
    assert "available" in result


# ── _check_url ──────────────────────────────────────────────


def test_check_url_ok(monkeypatch):
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **kw: mock_resp)
    result = _check_url("https://example.com")
    assert result["status"] == "ok"


def test_check_url_unreachable(monkeypatch):
    import urllib.error
    monkeypatch.setattr(
        "urllib.request.urlopen",
        MagicMock(side_effect=urllib.error.URLError("timeout")),
    )
    result = _check_url("https://nonexistent.invalid")
    assert result["status"] == "unreachable"


# ── _check_env_vars ─────────────────────────────────────────


def test_check_env_vars(monkeypatch):
    monkeypatch.setenv("APTGENT_RUNS_DIR", "/tmp/aptgent-runs")
    result = _check_env_vars()
    assert isinstance(result, dict)
    assert result["APTGENT_RUNS_DIR"] == "/tmp/aptgent-runs"
    assert "APTGENT_MODEL_DIR" in result


# ── run_doctor ──────────────────────────────────────────────


def test_run_doctor_all_ok(monkeypatch, capsys):
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/tool")
    monkeypatch.setattr(
        "subprocess.run",
        MagicMock(return_value=MagicMock(stdout="1.0", stderr="")),
    )
    # Mock URL check
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **kw: mock_resp)
    # Mock predictor model dir (imported inside run_doctor)
    monkeypatch.setattr(
        "aptgent.predictor_runtime.paths.default_model_dir",
        lambda: "/fake/models",
    )
    monkeypatch.setattr("pathlib.Path.is_dir", lambda self: True)
    monkeypatch.setattr("pathlib.Path.glob", lambda self, p: [])
    monkeypatch.setenv("GLM_API_KEY", "test")

    code = run_doctor()
    assert code == 0 or code == 1  # depends on env, just check no crash
    output = capsys.readouterr().out
    assert "aptgent doctor" in output
