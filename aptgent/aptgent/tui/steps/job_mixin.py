# aptgent/aptgen/tui/steps/job_mixin.py
"""Mixin for TUI step handlers that need detachable worker support.

Provides attach_or_spawn_job() which either:
1. Attaches to a running job (tail events.jsonl),
2. Loads completed results (job already done),
3. Or spawns a new detached subprocess.
"""
from __future__ import annotations

import logging
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

from aptgent.jobs.events import EventReader, read_last_event
from aptgent.jobs.pid import is_pid_alive, read_pid
from aptgent.workflow.persistence import Persistence

_log = logging.getLogger(__name__)


def is_job_alive(persistence: Persistence, run_id: str, step: str) -> bool:
    """Check whether a detached job process is still running."""
    pid_file = persistence.job_pid_file(run_id, step)
    pid = read_pid(pid_file)
    if pid is None:
        return False
    return is_pid_alive(pid)


def is_job_done(persistence: Persistence, run_id: str, step: str) -> bool:
    """Check whether a detached job has completed (has a done event)."""
    events_file = persistence.job_events_file(run_id, step)
    last = read_last_event(events_file)
    return last is not None and last.get("type") == "done"


def spawn_detached_job(app: Any, run_id: str, step: str) -> int:
    """Spawn a detached subprocess for the given run+step.

    Returns the PID of the spawned process.
    """
    persistence: Persistence = app.persistence
    persistence.ensure_job_dir(run_id, step)

    log_dir = persistence.run_dir(run_id) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stderr_log = log_dir / f"job_{step}.log"

    cmd = [sys.executable, "-m", "aptgent", "run-job", run_id, step]
    stderr_fd = open(stderr_log, "a")  # noqa: SIM115
    proc = subprocess.Popen(
        cmd,
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=stderr_fd,
    )
    stderr_fd.close()
    _log.info("Spawned detached job: pid=%d run=%s step=%s", proc.pid, run_id, step)
    return proc.pid


class JobAttachMixin:
    """Mixin for StepHandler subclasses that run detachable jobs.

    Subclasses must set JOB_STEP to the step name string
    (e.g. "candidate_enumeration").
    """

    JOB_STEP: str = ""

    def attach_or_spawn_job(
        self,
        *,
        on_event: Callable[[dict], None],
        on_done: Callable[[dict], None],
        on_error: Callable[[str], None],
        activity: str = "Running job...",
    ) -> None:
        screen = self.screen  # type: ignore[attr-defined]
        app = screen.app
        state = app.current_state
        run_id = state.run_id
        step = self.JOB_STEP
        persistence: Persistence = app.persistence

        screen.show_activity(activity)
        screen.set_input_enabled(False)

        # Case 1: Job already done
        if is_job_done(persistence, run_id, step):
            _log.info("Job already done for %s/%s, loading results", run_id, step)
            events_file = persistence.job_events_file(run_id, step)
            last = read_last_event(events_file)
            if last is not None:
                on_done(last.get("summary", {}))
            return

        # Case 2: Job is alive
        if is_job_alive(persistence, run_id, step):
            _log.info("Attaching to running job for %s/%s", run_id, step)
            self._tail_events(run_id, step, on_event, on_done, on_error)
            return

        # Case 3: Spawn new or restart (clean stale state first)
        events_file = persistence.job_events_file(run_id, step)
        has_partial = events_file.exists() and events_file.stat().st_size > 0
        if has_partial:
            _log.info("Partial events found for %s/%s, restarting job", run_id, step)
        else:
            _log.info("No existing job for %s/%s, spawning new", run_id, step)

        persistence.ensure_job_dir(run_id, step)
        for f in (
            persistence.job_pid_file(run_id, step),
            persistence.job_events_file(run_id, step),
            persistence.job_cmd_file(run_id, step),
            persistence.job_status_file(run_id, step),
        ):
            try:
                f.unlink(missing_ok=True)
            except OSError:
                pass

        pid = spawn_detached_job(app, run_id, step)
        screen.add_system_message(f"Detached job started (PID {pid})")

        self._tail_events(run_id, step, on_event, on_done, on_error)

    def _tail_events(
        self,
        run_id: str,
        step: str,
        on_event: Callable[[dict], None],
        on_done: Callable[[dict], None],
        on_error: Callable[[str], None],
    ) -> None:
        """Spawn a Textual worker that tails events.jsonl."""
        screen = self.screen  # type: ignore[attr-defined]
        persistence: Persistence = screen.app.persistence

        def _tail_worker() -> None:
            events_file = persistence.job_events_file(run_id, step)
            reader = EventReader(events_file)

            # Wait for the file to appear
            startup_timeout = screen.app.config.get("job_startup_timeout_seconds", 30)
            deadline = time.monotonic() + startup_timeout
            while not events_file.exists() and time.monotonic() < deadline:
                time.sleep(0.5)

            if not events_file.exists():
                screen.app.call_from_thread(on_error, "Timed out waiting for job to start")
                return

            offset = 0
            seen_done = False

            while not seen_done:
                current_size = reader.file_size()
                if current_size > offset:
                    for evt in reader.iter_events_from(offset):
                        etype = evt.get("type", "")

                        if etype == "done":
                            seen_done = True
                            screen.app.call_from_thread(on_done, evt.get("summary", {}))
                            break
                        elif etype == "error":
                            seen_done = True
                            screen.app.call_from_thread(on_error, evt.get("message", "Unknown error"))
                            break
                        elif etype in ("progress", "hit"):
                            screen.app.call_from_thread(on_event, evt)

                    offset = current_size

                if not seen_done:
                    pid_file = persistence.job_pid_file(run_id, step)
                    pid = read_pid(pid_file)
                    if pid is not None and not is_pid_alive(pid):
                        time.sleep(1)
                        current_size = reader.file_size()
                        if current_size > offset:
                            for evt in reader.iter_events_from(offset):
                                etype = evt.get("type", "")
                                if etype == "done":
                                    seen_done = True
                                    screen.app.call_from_thread(on_done, evt.get("summary", {}))
                                    break
                                elif etype == "error":
                                    seen_done = True
                                    screen.app.call_from_thread(on_error, evt.get("message", "Unknown error"))
                                    break
                            offset = current_size
                        if not seen_done:
                            screen.app.call_from_thread(on_error, "Job process exited unexpectedly")
                            return

                    time.sleep(0.5)

        screen.run_worker(_tail_worker, exclusive=True, thread=True)
