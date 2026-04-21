"""Tests for the detachable worker architecture."""

from __future__ import annotations

import json
import time

import pytest

from aptgent.jobs.events import EventWriter, EventReader, read_last_event


class TestEventProtocol:
    def test_writer_creates_events_jsonl(self, tmp_path):
        writer = EventWriter(tmp_path / "events.jsonl")
        writer.write_started(pid=12345)
        writer.close()

        lines = (tmp_path / "events.jsonl").read_text().strip().splitlines()
        assert len(lines) == 1
        evt = json.loads(lines[0])
        assert evt["type"] == "started"
        assert evt["pid"] == 12345
        assert "ts" in evt

    def test_writer_progress_and_hit(self, tmp_path):
        writer = EventWriter(tmp_path / "events.jsonl")
        writer.write_started(pid=99)
        writer.write_progress(done=500, total=1000, extra={"binding": 12})
        writer.write_hit(candidate_id="cand_0", probability=0.92)
        writer.write_done(summary={"total": 1000, "hits": 12})
        writer.close()

        lines = (tmp_path / "events.jsonl").read_text().strip().splitlines()
        assert len(lines) == 4
        types = [json.loads(l)["type"] for l in lines]
        assert types == ["started", "progress", "hit", "done"]

    def test_writer_error(self, tmp_path):
        writer = EventWriter(tmp_path / "events.jsonl")
        writer.write_error(message="boom")
        writer.close()

        evt = json.loads((tmp_path / "events.jsonl").read_text().strip())
        assert evt["type"] == "error"
        assert evt["message"] == "boom"

    def test_writer_heartbeat(self, tmp_path):
        writer = EventWriter(tmp_path / "events.jsonl")
        writer.write_heartbeat()
        writer.close()

        evt = json.loads((tmp_path / "events.jsonl").read_text().strip())
        assert evt["type"] == "heartbeat"

    def test_reader_reads_events(self, tmp_path):
        path = tmp_path / "events.jsonl"
        path.write_text(
            '{"type":"started","ts":"t1","pid":1}\n'
            '{"type":"progress","ts":"t2","done":5,"total":10}\n'
        )
        reader = EventReader(path)
        events = list(reader.iter_events())
        assert len(events) == 2
        assert events[0]["type"] == "started"
        assert events[1]["done"] == 5

    def test_read_last_event(self, tmp_path):
        path = tmp_path / "events.jsonl"
        path.write_text(
            '{"type":"started","ts":"t1","pid":1}\n'
            '{"type":"done","ts":"t2","summary":{}}\n'
        )
        evt = read_last_event(path)
        assert evt is not None
        assert evt["type"] == "done"

    def test_read_last_event_empty(self, tmp_path):
        path = tmp_path / "events.jsonl"
        assert read_last_event(path) is None

    def test_read_last_event_missing(self, tmp_path):
        assert read_last_event(tmp_path / "nope.jsonl") is None


from aptgent.workflow.persistence import Persistence


class TestPersistenceJobHelpers:
    def test_job_dir_returns_correct_path(self, tmp_path):
        p = Persistence(runs_dir=tmp_path)
        p.init_run("run1")
        jd = p.job_dir("run1", "candidate_enumeration")
        assert jd == tmp_path / "run1" / "jobs" / "candidate_enumeration"

    def test_job_pid_file(self, tmp_path):
        p = Persistence(runs_dir=tmp_path)
        p.init_run("run1")
        assert p.job_pid_file("run1", "candidate_enumeration") == (
            tmp_path / "run1" / "jobs" / "candidate_enumeration" / "pid"
        )

    def test_job_events_file(self, tmp_path):
        p = Persistence(runs_dir=tmp_path)
        p.init_run("run1")
        assert p.job_events_file("run1", "candidate_enumeration") == (
            tmp_path / "run1" / "jobs" / "candidate_enumeration" / "events.jsonl"
        )

    def test_job_cmd_file(self, tmp_path):
        p = Persistence(runs_dir=tmp_path)
        p.init_run("run1")
        assert p.job_cmd_file("run1", "candidate_enumeration") == (
            tmp_path / "run1" / "jobs" / "candidate_enumeration" / "cmd.jsonl"
        )

    def test_job_status_file(self, tmp_path):
        p = Persistence(runs_dir=tmp_path)
        p.init_run("run1")
        assert p.job_status_file("run1", "candidate_enumeration") == (
            tmp_path / "run1" / "jobs" / "candidate_enumeration" / "status"
        )

    def test_ensure_job_dir_creates_directory(self, tmp_path):
        p = Persistence(runs_dir=tmp_path)
        p.init_run("run1")
        p.ensure_job_dir("run1", "docking_run")
        assert (tmp_path / "run1" / "jobs" / "docking_run").is_dir()


import os

from aptgent.jobs.pid import is_pid_alive, read_pid, write_pid, clear_pid


class TestPidUtils:
    def test_read_pid_returns_int(self, tmp_path):
        pid_file = tmp_path / "pid"
        pid_file.write_text(str(os.getpid()))
        assert read_pid(pid_file) == os.getpid()

    def test_read_pid_returns_none_on_missing(self, tmp_path):
        assert read_pid(tmp_path / "nope") is None

    def test_read_pid_returns_none_on_empty(self, tmp_path):
        pid_file = tmp_path / "pid"
        pid_file.write_text("")
        assert read_pid(pid_file) is None

    def test_write_pid_creates_file(self, tmp_path):
        pid_file = tmp_path / "pid"
        write_pid(pid_file, 12345)
        assert pid_file.read_text().strip() == "12345"

    def test_clear_pid_removes_file(self, tmp_path):
        pid_file = tmp_path / "pid"
        pid_file.write_text("12345")
        clear_pid(pid_file)
        assert not pid_file.exists()

    def test_clear_pid_noop_on_missing(self, tmp_path):
        clear_pid(tmp_path / "nope")  # should not raise

    def test_is_pid_alive_for_current_process(self):
        assert is_pid_alive(os.getpid()) is True

    def test_is_pid_alive_for_init(self):
        assert is_pid_alive(1) is True

    def test_is_pid_alive_for_unlikely_pid(self):
        assert is_pid_alive(999999999) is False


from aptgent.jobs.runner import build_parser, _JOB_RUNNERS


class TestJobRunnerCLI:
    def test_parser_accepts_run_job(self):
        parser = build_parser()
        args = parser.parse_args(["run-job", "run1", "candidate_enumeration"])
        assert args.run_id == "run1"
        assert args.step == "candidate_enumeration"
        assert args.foreground is False

    def test_parser_accepts_foreground(self):
        parser = build_parser()
        args = parser.parse_args(["run-job", "run1", "docking_run", "--foreground"])
        assert args.foreground is True

    def test_job_runners_registry_has_enum_and_docking(self):
        assert "candidate_enumeration" in _JOB_RUNNERS
        assert "docking_run" in _JOB_RUNNERS

    def test_job_runners_registry_only_has_known_steps(self):
        for step_name in _JOB_RUNNERS:
            assert step_name in ("candidate_enumeration", "docking_run")


import subprocess
from unittest.mock import MagicMock, patch

from aptgent.tui.steps.job_mixin import is_job_done, is_job_alive, spawn_detached_job


class TestJobAttachMixin:
    def test_is_job_done_with_done_event(self, tmp_path):
        p = Persistence(runs_dir=tmp_path)
        p.init_run("r1")
        p.ensure_job_dir("r1", "candidate_enumeration")
        events = p.job_events_file("r1", "candidate_enumeration")
        events.write_text('{"type":"started","ts":"t1","pid":1}\n{"type":"done","ts":"t2"}\n')
        assert is_job_done(p, "r1", "candidate_enumeration") is True

    def test_is_job_done_without_done_event(self, tmp_path):
        p = Persistence(runs_dir=tmp_path)
        p.init_run("r1")
        p.ensure_job_dir("r1", "candidate_enumeration")
        events = p.job_events_file("r1", "candidate_enumeration")
        events.write_text('{"type":"started","ts":"t1","pid":1}\n')
        assert is_job_done(p, "r1", "candidate_enumeration") is False

    def test_is_job_done_no_events_file(self, tmp_path):
        p = Persistence(runs_dir=tmp_path)
        p.init_run("r1")
        assert is_job_done(p, "r1", "candidate_enumeration") is False

    def test_is_job_alive_with_current_pid(self, tmp_path):
        p = Persistence(runs_dir=tmp_path)
        p.init_run("r1")
        p.ensure_job_dir("r1", "candidate_enumeration")
        pid_file = p.job_pid_file("r1", "candidate_enumeration")
        pid_file.write_text(str(os.getpid()))
        assert is_job_alive(p, "r1", "candidate_enumeration") is True

    def test_is_job_alive_with_dead_pid(self, tmp_path):
        p = Persistence(runs_dir=tmp_path)
        p.init_run("r1")
        p.ensure_job_dir("r1", "candidate_enumeration")
        pid_file = p.job_pid_file("r1", "candidate_enumeration")
        pid_file.write_text("999999999")
        assert is_job_alive(p, "r1", "candidate_enumeration") is False

    def test_is_job_alive_no_pid_file(self, tmp_path):
        p = Persistence(runs_dir=tmp_path)
        p.init_run("r1")
        assert is_job_alive(p, "r1", "candidate_enumeration") is False

    def test_spawn_detached_job_creates_process(self, tmp_path):
        p = Persistence(runs_dir=tmp_path)
        p.init_run("r1")
        mock_app = MagicMock()
        mock_app.persistence = p

        with patch("aptgent.tui.steps.job_mixin.subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.pid = 12345
            mock_popen.return_value = mock_proc
            pid = spawn_detached_job(mock_app, "r1", "candidate_enumeration")
            assert pid == 12345
            mock_popen.assert_called_once()
            call_kwargs = mock_popen.call_args.kwargs
            assert call_kwargs.get("start_new_session") is True
