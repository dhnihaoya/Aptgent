"""Tests for aptgent.protocol.cancel — CmdFileCancelPoller."""
from __future__ import annotations

import threading
import time
from pathlib import Path

from aptgent.protocol.cancel import CmdFileCancelPoller


def test_cmd_file_cancel_poller_sets_event(tmp_path: Path):
    cmd_file = tmp_path / "cmd.jsonl"
    cancel_event = threading.Event()
    stop_event = threading.Event()

    cmd_file.write_text("cancel")
    poller = CmdFileCancelPoller(cmd_file, cancel_event, stop_event, interval=0.05)

    assert cancel_event.wait(timeout=2)
    stop_event.set()
    poller.join(timeout=2)


def test_cmd_file_cancel_poller_ignores_non_cancel(tmp_path: Path):
    cmd_file = tmp_path / "cmd.jsonl"
    cancel_event = threading.Event()
    stop_event = threading.Event()

    cmd_file.write_text("something_else")
    _poller = CmdFileCancelPoller(cmd_file, cancel_event, stop_event, interval=0.05)

    time.sleep(0.15)
    assert not cancel_event.is_set()
    stop_event.set()
    _poller.join(timeout=2)


def test_cmd_file_cancel_poller_stops_on_stop_event(tmp_path: Path):
    cmd_file = tmp_path / "cmd.jsonl"
    cancel_event = threading.Event()
    stop_event = threading.Event()

    poller = CmdFileCancelPoller(cmd_file, cancel_event, stop_event, interval=0.05)
    stop_event.set()
    poller.join(timeout=2)
    assert not cancel_event.is_set()


def test_cmd_file_cancel_poller_no_file(tmp_path: Path):
    cmd_file = tmp_path / "nonexistent.jsonl"
    cancel_event = threading.Event()
    stop_event = threading.Event()

    _poller = CmdFileCancelPoller(cmd_file, cancel_event, stop_event, interval=0.05)
    time.sleep(0.15)
    assert not cancel_event.is_set()
    stop_event.set()
    _poller.join(timeout=2)
