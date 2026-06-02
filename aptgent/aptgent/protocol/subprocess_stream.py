"""Subprocess session with streaming line-JSON output and cooperative cancel."""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from typing import Any, Callable

from aptgent.protocol.line_json import iter_jsonl

_log = logging.getLogger(__name__)


class SubprocessSession:
    """Manage a subprocess that emits line-delimited JSON on stdout.

    Handles:
    - stdout line-JSON parsing (error messages intercepted separately)
    - stderr drain thread
    - cooperative cancel (writes ``cancel\\n`` to stdin)
    - three-stage termination: wait(30s) → terminate → wait(10s) → kill → wait(5s)

    Usage::

        session = SubprocessSession(cmd, env=os.environ.copy(), cwd=project_root)
        rc, stderr, timed_out = session.run(
            on_line=callback,
            cancel_event=event,
            timeout_seconds=3600,
        )
    """

    def __init__(
        self,
        cmd: list[str],
        *,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> None:
        self._cmd = cmd
        self._env = env or os.environ.copy()
        self._cwd = cwd

    def run(
        self,
        *,
        on_line: Callable[[dict], None],
        cancel_event: threading.Event | None = None,
        timeout_seconds: int | None = None,
        shutdown_waits: tuple[float, float, float] = (30, 10, 5),
    ) -> tuple[int, str, bool]:
        """Spawn the subprocess and block until it exits.

        Returns ``(returncode, stderr_output, timed_out)``.
        Raises :class:`RuntimeError` if the subprocess reports an ``error``
        message in its JSONL output.
        """
        proc = subprocess.Popen(
            self._cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE,
            bufsize=1,
            text=True,
            cwd=self._cwd,
            env=self._env,
            start_new_session=True,
        )

        stderr_chunks: list[str] = []
        subprocess_error: dict[str, Any] = {}

        def _stdout_reader() -> None:
            try:
                for obj in iter_jsonl(proc.stdout):
                    if obj.get("type") == "error":
                        subprocess_error["message"] = obj.get("message", "")
                        continue
                    try:
                        on_line(obj)
                    except Exception as exc:
                        _log.warning("streaming on_line callback raised: %s", exc)
            except Exception as exc:
                _log.warning("streaming stdout reader aborted: %s", exc)

        def _stderr_pump() -> None:
            try:
                for line in proc.stderr:
                    stderr_chunks.append(line)
            except Exception as exc:
                _log.debug("streaming stderr pump aborted: %s", exc)

        reader_thread = threading.Thread(target=_stdout_reader, daemon=True)
        stderr_thread = threading.Thread(target=_stderr_pump, daemon=True)
        reader_thread.start()
        stderr_thread.start()

        timed_out = False
        start = time.monotonic()

        def _send_cancel() -> None:
            try:
                if proc.stdin and not proc.stdin.closed:
                    proc.stdin.write("cancel\n")
                    proc.stdin.flush()
            except (OSError, ValueError):
                pass

        try:
            while reader_thread.is_alive():
                reader_thread.join(timeout=0.5)
                if cancel_event is not None and cancel_event.is_set():
                    _send_cancel()
                    break
                if timeout_seconds is not None and (time.monotonic() - start) > timeout_seconds:
                    timed_out = True
                    _log.warning(
                        "streaming subprocess exceeded %ss; requesting cancel.",
                        timeout_seconds,
                    )
                    _send_cancel()
                    break
        finally:
            wait_first, wait_terminate, wait_kill = shutdown_waits
            try:
                proc.wait(timeout=wait_first)
            except subprocess.TimeoutExpired:
                _log.warning("streaming subprocess did not exit; terminating.")
                proc.terminate()
                try:
                    proc.wait(timeout=wait_terminate)
                except subprocess.TimeoutExpired:
                    _log.warning("streaming subprocess still alive; killing.")
                    proc.kill()
                    try:
                        proc.wait(timeout=wait_kill)
                    except subprocess.TimeoutExpired:
                        _log.critical(
                            "subprocess pid %d survived SIGKILL; possible orphan process",
                            proc.pid,
                        )
            reader_thread.join(timeout=5)
            stderr_thread.join(timeout=5)
            try:
                if proc.stdout:
                    proc.stdout.close()
                if proc.stderr:
                    proc.stderr.close()
                if proc.stdin:
                    proc.stdin.close()
            except OSError:
                pass

        stderr_output = "".join(stderr_chunks)
        if timed_out and cancel_event is not None:
            cancel_event.set()

        if subprocess_error:
            raise RuntimeError(
                "Predictor subprocess reported error: "
                f"{subprocess_error.get('message', '')[:500]}"
            )

        return proc.returncode, stderr_output, timed_out
