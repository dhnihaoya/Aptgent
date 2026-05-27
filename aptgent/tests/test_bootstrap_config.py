"""Tests for ``aptgent.bootstrap.config``."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from aptgent.bootstrap.config import (
    AppConfigBundle,
    expand_env,
    load_config,
    _expand_config,
    _load_toml,
)


# ── expand_env ──────────────────────────────────────────────


def test_expand_env_plain_var(monkeypatch):
    monkeypatch.setenv("APTGENT_TEST_VAR", "hello")
    assert expand_env("${APTGENT_TEST_VAR}") == "hello"


def test_expand_env_default_used(monkeypatch):
    monkeypatch.delenv("APTGENT_MISSING_VAR", raising=False)
    assert expand_env("${APTGENT_MISSING_VAR:-fallback}") == "fallback"


def test_expand_env_default_ignored_when_set(monkeypatch):
    monkeypatch.setenv("APTGENT_TEST_VAR", "real")
    assert expand_env("${APTGENT_TEST_VAR:-fallback}") == "real"


def test_expand_env_tilde():
    assert expand_env("~") == os.path.expanduser("~")
    assert expand_env("~/some/path") == os.path.expanduser("~/some/path")


def test_expand_env_no_match(monkeypatch):
    monkeypatch.delenv("APTGENT_ZZZ_NONEXISTENT", raising=False)
    result = expand_env("${APTGENT_ZZZ_NONEXISTENT}")
    assert result == "${APTGENT_ZZZ_NONEXISTENT}"


def test_expand_env_mixed():
    result = expand_env("plain_text")
    assert result == "plain_text"


# ── _expand_config ──────────────────────────────────────────


def test_expand_config_nested(monkeypatch):
    monkeypatch.setenv("APTGENT_TEST_DIR", "/tmp/runs")
    raw = {"paths": {"runs_dir": "${APTGENT_TEST_DIR}"}}
    result = _expand_config(raw)
    assert result["paths"]["runs_dir"] == "/tmp/runs"


def test_expand_config_list_values(monkeypatch):
    monkeypatch.setenv("APTGENT_TEST_ITEM", "v1")
    raw = {"items": ["${APTGENT_TEST_ITEM}", "static"]}
    result = _expand_config(raw)
    assert result["items"] == ["v1", "static"]


def test_expand_config_non_string_preserved():
    raw = {"count": 42, "flag": True, "nested": {"n": None}}
    result = _expand_config(raw)
    assert result["count"] == 42
    assert result["flag"] is True
    assert result["nested"]["n"] is None


# ── _load_toml ──────────────────────────────────────────────


def test_load_toml_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        _load_toml(tmp_path / "nonexistent.toml")


def test_load_toml_valid(tmp_path):
    p = tmp_path / "test.toml"
    p.write_text('[section]\nkey = "value"\n', encoding="utf-8")
    result = _load_toml(p)
    assert result["section"]["key"] == "value"


# ── load_config ─────────────────────────────────────────────


def test_load_config_returns_bundle():
    bundle = load_config()
    assert isinstance(bundle, AppConfigBundle)
    assert isinstance(bundle.workflow, dict)
    assert isinstance(bundle.tools, dict)
    assert isinstance(bundle.llm, dict)


def test_load_config_custom_dir(tmp_path):
    (tmp_path / "workflow.toml").write_text('[paths]\nruns_dir = "/tmp/r"\n', encoding="utf-8")
    (tmp_path / "tools.toml").write_text('[rna_fold]\ncommand = "RNAfold"\n', encoding="utf-8")
    (tmp_path / "llm.toml").write_text('[provider]\n', encoding="utf-8")
    bundle = load_config(config_dir=tmp_path)
    assert bundle.workflow["paths"]["runs_dir"] == "/tmp/r"
