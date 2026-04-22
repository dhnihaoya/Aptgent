from __future__ import annotations

from aptgent.jobs.runner import _JOB_RUNNERS, build_parser


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
