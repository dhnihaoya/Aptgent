"""Tests for aptgent.protocol.subprocess_stream — SubprocessSession."""
from __future__ import annotations

import sys
import threading

from aptgent.protocol.subprocess_stream import SubprocessSession

_BLOCK_ON_STDIN_SCRIPT = (
    'import json,sys;'
    'sys.stdout.write(json.dumps({"type":"ready"})+chr(10));sys.stdout.flush();'
    'sys.stdin.readline()'
)


def test_session_captures_stdout_json_lines():
    cmd = [
        sys.executable, "-c",
        'import json,sys;'
        'sys.stdout.write(json.dumps({"type":"ready"})+chr(10));'
        'sys.stdout.write(json.dumps({"type":"done"})+chr(10))',
    ]
    received: list[dict] = []
    session = SubprocessSession(cmd)
    rc, stderr, timed_out = session.run(on_line=lambda obj: received.append(obj))
    assert rc == 0
    assert not timed_out
    assert len(received) == 2
    assert received[0]["type"] == "ready"
    assert received[1]["type"] == "done"


def test_session_intercepts_error_events():
    cmd = [
        sys.executable, "-c",
        'import json,sys;'
        'sys.stdout.write(json.dumps({"type":"error","message":"boom"})+chr(10))',
    ]
    received: list[dict] = []
    session = SubprocessSession(cmd)
    try:
        session.run(on_line=lambda obj: received.append(obj))
        assert False, "should have raised RuntimeError"
    except RuntimeError as exc:
        assert "boom" in str(exc)
    assert received == []


def test_session_collects_stderr():
    cmd = [
        sys.executable, "-c",
        'import sys;'
        'sys.stderr.write("warning line\\n");'
        'sys.stdout.write("{}\\n")',
    ]
    received: list[dict] = []
    session = SubprocessSession(cmd)
    rc, stderr, _ = session.run(on_line=lambda obj: received.append(obj))
    assert rc == 0
    assert "warning line" in stderr


def test_session_cancel_event():
    """Cancel event should stop the subprocess via stdin cancel."""
    cmd = [sys.executable, "-c", _BLOCK_ON_STDIN_SCRIPT]
    cancel = threading.Event()
    received: list[dict] = []

    def _on_line(obj):
        received.append(obj)
        cancel.set()

    session = SubprocessSession(cmd)
    rc, stderr, timed_out = session.run(
        on_line=_on_line, cancel_event=cancel,
    )
    assert len(received) >= 1
    assert received[0]["type"] == "ready"
    assert not timed_out


def test_session_timeout():
    """Timeout should trigger timed_out=True when subprocess runs too long."""
    cmd = [sys.executable, "-c", _BLOCK_ON_STDIN_SCRIPT]
    received: list[dict] = []
    session = SubprocessSession(cmd)
    rc, stderr, timed_out = session.run(
        on_line=lambda obj: received.append(obj),
        timeout_seconds=1,
    )
    assert timed_out


def test_session_unresponsive_subprocess_terminates():
    """When subprocess ignores stdin cancel, terminate/kill fallback must work."""
    cmd = [
        sys.executable, "-c",
        'import json,sys,time;'
        'sys.stdout.write(json.dumps({"type":"ready"})+chr(10));sys.stdout.flush();'
        'time.sleep(300)',
    ]
    received: list[dict] = []
    session = SubprocessSession(cmd)
    rc, stderr, timed_out = session.run(
        on_line=lambda obj: received.append(obj),
        timeout_seconds=0.2,
        shutdown_waits=(0.2, 0.2, 0.2),
    )
    assert timed_out
    assert rc is not None
