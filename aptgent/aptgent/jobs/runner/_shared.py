"""Shared infrastructure for detached job runners (heartbeat, persistence)."""
from __future__ import annotations

import atexit
import logging
import os
import threading
from typing import Any, Callable

from aptgent.bootstrap.config import load_config
from aptgent.jobs.events import EventWriter
from aptgent.jobs.pid import clear_pid, write_pid
from aptgent.workflow.engine import WorkflowEngine
from aptgent.workflow.persistence import Persistence

_log = logging.getLogger(__name__)

_HEARTBEAT_INTERVAL = 10


def _build_persistence() -> Persistence:
    bundle = load_config()
    return Persistence(bundle.workflow.get("paths", {}).get("runs_dir", "./runs"))


def _write_heartbeat_loop(writer: EventWriter, stop: threading.Event) -> None:
    while not stop.is_set():
        stop.wait(_HEARTBEAT_INTERVAL)
        if not stop.is_set():
            try:
                writer.write_heartbeat()
            except Exception:
                _log.warning("Heartbeat write failed", exc_info=True)


def _run_with_heartbeat(
    run_id: str,
    step: str,
    persistence: Persistence,
    body: Callable[[EventWriter, Any, Persistence], None],
) -> int:
    pid_file = persistence.job_pid_file(run_id, step)
    events_file = persistence.job_events_file(run_id, step)
    cmd_file = persistence.job_cmd_file(run_id, step)
    status_file = persistence.job_status_file(run_id, step)

    # Clear stale cancel commands
    try:
        cmd_file.unlink(missing_ok=True)
    except OSError:
        pass

    try:
        status_file.write_text("starting")
        atexit.register(lambda: status_file.unlink(missing_ok=True))
    except OSError:
        pass

    writer = EventWriter(events_file)

    if not write_pid(pid_file, os.getpid()):
        writer.write_error(message="Another job process is already running for this step")
        writer.close()
        return 1
    atexit.register(clear_pid, pid_file)

    status_file.write_text("running")
    writer.write_started(pid=os.getpid())

    stop_heartbeat = threading.Event()
    heartbeat_thread = threading.Thread(
        target=_write_heartbeat_loop, args=(writer, stop_heartbeat), daemon=True
    )
    heartbeat_thread.start()

    state = None
    try:
        state = persistence.load(run_id)
        if state is None:
            writer.write_error(message=f"Run state not found: {run_id}")
            return 1

        body(writer, state, persistence)
        return 0
    except Exception as exc:
        _log.exception("Job runner failed")
        try:
            writer.write_error(message=str(exc))
        except Exception:
            _log.warning("Failed to write error event", exc_info=True)
        if state is not None:
            try:
                engine = WorkflowEngine(persistence)
                engine.mark_error(state, str(exc))
            except Exception:
                _log.warning("Failed to mark_error on state", exc_info=True)
        return 1
    finally:
        stop_heartbeat.set()
        heartbeat_thread.join(timeout=2)
        writer.close()
