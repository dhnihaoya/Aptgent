from __future__ import annotations

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


from aptgent.jobs.pid import is_pid_alive, read_pid, write_pid, clear_pid
