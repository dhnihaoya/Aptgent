"""Detached job runners: ``python -m aptgent run-job <run_id> <step>``.

Each runner loads RunState from the persistence layer, executes the
step logic in an isolated process, and writes events to
runs/<id>/jobs/<step>/events.jsonl.
"""
from __future__ import annotations

import argparse
import logging
import sys
from typing import Any, Callable

from aptgent.jobs.events import EventWriter
from aptgent.workflow.persistence import Persistence

from .docking import _run_docking
from .enumeration import _run_enumeration
from ._shared import _build_persistence, _run_with_heartbeat
from .specificity import _run_specificity

_log = logging.getLogger(__name__)

_JOB_RUNNERS: dict[str, Callable[[EventWriter, Any, Persistence], None]] = {
    "candidate_enumeration": _run_enumeration,
    "specificity_filter": _run_specificity,
    "docking_run": _run_docking,
}


def run_job(run_id: str, step: str, *, persistence: Persistence | None = None) -> int:
    """Main entry: load state, dispatch to runner, write events."""
    pers = persistence or _build_persistence()
    runner_fn = _JOB_RUNNERS.get(step)
    if runner_fn is None:
        print(f"Unknown step for detached execution: {step}", file=sys.stderr)
        return 1

    return _run_with_heartbeat(run_id, step, pers, runner_fn)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aptgent",
        description="Aptamer design workflow agent.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_job_parser = sub.add_parser(
        "run-job",
        help="Run a workflow step as a detached job.",
    )
    run_job_parser.add_argument("run_id", help="The run to execute")
    run_job_parser.add_argument("step", help="The step to run")
    run_job_parser.add_argument("--foreground", action="store_true", help="Run in foreground (debug)")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "run-job":
        logging.basicConfig(
            level=logging.DEBUG if getattr(args, "foreground", False) else logging.INFO,
            format="%(asctime)s %(name)s %(levelname)s %(message)s",
        )
        return run_job(args.run_id, args.step)

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
