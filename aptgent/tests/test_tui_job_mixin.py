from __future__ import annotations

import os
import subprocess
from unittest.mock import MagicMock, patch

from aptgent.domain.enums import Step
from aptgent.jobs.events import EventReader, EventWriter
from aptgent.tui.steps.job_mixin import is_job_alive, is_job_done, spawn_detached_job
from aptgent.workflow.persistence import Persistence


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
class TestDetachedWorkerSpawn:
    """test_detached_worker_spawn: mock Popen, verify start_new_session + pid file."""

    def test_spawn_creates_pid_file_and_uses_start_new_session(self, tmp_path):
        from aptgent.tui.steps.job_mixin import spawn_detached_job

        p = Persistence(runs_dir=tmp_path)
        p.init_run("r1")
        mock_app = MagicMock()
        mock_app.persistence = p

        with patch("aptgent.tui.steps.job_mixin.subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.pid = 42424
            mock_popen.return_value = mock_proc

            pid = spawn_detached_job(mock_app, "r1", "candidate_enumeration")
            assert pid == 42424

            call_kwargs = mock_popen.call_args.kwargs
            assert call_kwargs["start_new_session"] is True
            assert call_kwargs["stdout"] == subprocess.DEVNULL

    def test_spawn_uses_correct_command(self, tmp_path):
        from aptgent.tui.steps.job_mixin import spawn_detached_job

        p = Persistence(runs_dir=tmp_path)
        p.init_run("r1")
        mock_app = MagicMock()
        mock_app.persistence = p

        with patch("aptgent.tui.steps.job_mixin.subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.pid = 42
            mock_popen.return_value = mock_proc

            spawn_detached_job(mock_app, "r1", "docking_run")

            cmd = mock_popen.call_args.args[0]
            assert cmd[1] == "-m"
            assert cmd[2] == "aptgent"
            assert cmd[3] == "run-job"
            assert cmd[4] == "r1"
            assert cmd[5] == "docking_run"
class TestAttachToRunningJob:
    """test_attach_to_running_job: pre-write events.jsonl + live pid."""

    def test_detects_running_job_as_alive(self, tmp_path):
        p = Persistence(runs_dir=tmp_path)
        p.init_run("r1")
        p.ensure_job_dir("r1", "candidate_enumeration")

        pid_file = p.job_pid_file("r1", "candidate_enumeration")
        pid_file.write_text(str(os.getpid()))

        events_file = p.job_events_file("r1", "candidate_enumeration")
        from aptgent.jobs.events import EventWriter
        writer = EventWriter(events_file)
        writer.write_started(pid=os.getpid())
        writer.write_progress(done=100, total=1000, extra={"binding": 5})
        writer.close()

        assert is_job_alive(p, "r1", "candidate_enumeration") is True
        assert is_job_done(p, "r1", "candidate_enumeration") is False

    def test_detects_completed_job(self, tmp_path):
        p = Persistence(runs_dir=tmp_path)
        p.init_run("r1")
        p.ensure_job_dir("r1", "candidate_enumeration")

        events_file = p.job_events_file("r1", "candidate_enumeration")
        from aptgent.jobs.events import EventWriter
        writer = EventWriter(events_file)
        writer.write_started(pid=12345)
        writer.write_done(summary={"total": 1000, "hits": 42})
        writer.close()

        assert is_job_done(p, "r1", "candidate_enumeration") is True

    def test_reader_can_read_from_offset(self, tmp_path):
        from aptgent.jobs.events import EventWriter, EventReader

        events_file = tmp_path / "events.jsonl"
        writer = EventWriter(events_file)
        writer.write_started(pid=1)
        offset_after_start = events_file.stat().st_size
        writer.write_progress(done=500, total=1000)
        writer.write_done(summary={"total": 1000})
        writer.close()

        reader = EventReader(events_file)
        new_events = list(reader.iter_events_from(offset_after_start))
        assert len(new_events) == 2
        assert new_events[0]["type"] == "progress"
        assert new_events[1]["type"] == "done"
class TestResumeAfterTuiRestart:
    """test_resume_after_tui_restart: full events.jsonl + state stopped mid-step."""

    def test_resume_detects_done_event_after_crash(self, tmp_path):
        p = Persistence(runs_dir=tmp_path)
        state = p.init_run("r1")

        from aptgent.workflow.engine import WorkflowEngine
        engine = WorkflowEngine(p)
        engine.transition_to(state, Step.SECONDARY_STRUCTURE)
        engine.transition_to(state, Step.SITE_PROPOSAL)
        engine.transition_to(state, Step.CANDIDATE_ENUMERATION)

        p.ensure_job_dir("r1", "candidate_enumeration")
        events_file = p.job_events_file("r1", "candidate_enumeration")
        from aptgent.jobs.events import EventWriter
        writer = EventWriter(events_file)
        writer.write_started(pid=99999)
        writer.write_progress(done=256, total=256)
        writer.write_done(summary={"total": 256, "hits": 10, "kept": 10})
        writer.close()

        reloaded = p.load("r1")
        assert reloaded is not None
        assert reloaded.current_step == Step.CANDIDATE_ENUMERATION

        assert is_job_done(p, "r1", "candidate_enumeration") is True
        assert is_job_alive(p, "r1", "candidate_enumeration") is False

    def test_resume_detects_alive_job(self, tmp_path):
        p = Persistence(runs_dir=tmp_path)
        state = p.init_run("r1")

        p.ensure_job_dir("r1", "docking_run")
        pid_file = p.job_pid_file("r1", "docking_run")
        pid_file.write_text(str(os.getpid()))

        events_file = p.job_events_file("r1", "docking_run")
        from aptgent.jobs.events import EventWriter
        writer = EventWriter(events_file)
        writer.write_started(pid=os.getpid())
        writer.write_progress(done=2, total=10)
        writer.close()

        assert is_job_alive(p, "r1", "docking_run") is True
        assert is_job_done(p, "r1", "docking_run") is False
