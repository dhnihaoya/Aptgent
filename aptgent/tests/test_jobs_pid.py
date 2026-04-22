from __future__ import annotations

import os

from aptgent.jobs.pid import clear_pid, is_pid_alive, read_pid, write_pid


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
