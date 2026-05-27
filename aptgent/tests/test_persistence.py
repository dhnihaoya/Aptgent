"""Regression tests for ``Persistence`` on-disk layout and public API."""

from __future__ import annotations

import json

import pytest

from aptgent.workflow.persistence import CorruptedStateError, Persistence
from aptgent.workflow.state import RunState


def test_run_dir_is_public_and_validates_ids(tmp_path):
    persistence = Persistence(runs_dir=tmp_path)
    path = persistence.run_dir("my_run_1")
    assert path == tmp_path / "my_run_1"

    with pytest.raises(ValueError):
        persistence.run_dir("bad/run id")


def test_init_run_creates_layout_and_saves_state(tmp_path):
    persistence = Persistence(runs_dir=tmp_path)
    state = persistence.init_run("run_one")

    run_dir = persistence.run_dir("run_one")
    assert run_dir.is_dir()
    assert (run_dir / "artifacts").is_dir()
    assert (run_dir / "logs").is_dir()

    state_file = run_dir / "state.json"
    assert state_file.is_file()
    payload = json.loads(state_file.read_text(encoding="utf-8"))
    assert payload["run_id"] == "run_one"


def test_save_load_roundtrip(tmp_path):
    persistence = Persistence(runs_dir=tmp_path)
    state = persistence.init_run("round_trip")
    state.input_payload["note"] = "hello"
    persistence.save(state)

    reloaded = persistence.load("round_trip")
    assert reloaded is not None
    assert reloaded.input_payload.get("note") == "hello"


def test_load_missing_run_returns_none(tmp_path):
    persistence = Persistence(runs_dir=tmp_path)
    assert persistence.load("does_not_exist") is None


def test_load_corrupted_run_raises(tmp_path):
    persistence = Persistence(runs_dir=tmp_path)
    run_dir = persistence.run_dir("corrupted")
    run_dir.mkdir(parents=True)
    (run_dir / "state.json").write_text("NOT VALID JSON {{{", encoding="utf-8")

    with pytest.raises(CorruptedStateError):
        persistence.load("corrupted")


def test_init_run_rejects_existing_run(tmp_path):
    persistence = Persistence(runs_dir=tmp_path)
    persistence.init_run("existing")

    with pytest.raises(ValueError, match="already exists"):
        persistence.init_run("existing")


def test_list_runs_returns_sorted_ids(tmp_path):
    persistence = Persistence(runs_dir=tmp_path)
    persistence.init_run("run_b")
    persistence.init_run("run_a")
    persistence.init_run("run_c")
    assert persistence.list_runs() == ["run_a", "run_b", "run_c"]


def test_write_artifact_json(tmp_path):
    persistence = Persistence(runs_dir=tmp_path)
    persistence.init_run("with_artifacts")
    out = persistence.write_artifact(
        "with_artifacts", "final_report.json", {"score": 1.5}
    )
    assert out.is_file()
    assert json.loads(out.read_text(encoding="utf-8")) == {"score": 1.5}


def test_append_log_writes_jsonl(tmp_path):
    persistence = Persistence(runs_dir=tmp_path)
    persistence.init_run("log_me")
    persistence.append_log("log_me", {"event": "transition", "to_step": "intake"})
    persistence.append_log("log_me", {"event": "complete"})

    log_file = persistence.run_dir("log_me") / "logs" / "workflow.jsonl"
    lines = log_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["event"] == "transition"
    assert json.loads(lines[1])["event"] == "complete"
