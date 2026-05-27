from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from aptgent.workflow.state import RunState

_log = logging.getLogger(__name__)

_VALID_RUN_ID = re.compile(r"^[a-zA-Z0-9_\-]+$")


class Persistence:
    def __init__(self, runs_dir: str | Path = "./runs") -> None:
        self.runs_dir = Path(runs_dir)
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _validate_run_id(run_id: str) -> None:
        if not run_id or not _VALID_RUN_ID.match(run_id):
            raise ValueError(
                f"Invalid run_id '{run_id}': must be non-empty and contain only "
                "alphanumeric characters, hyphens, or underscores."
            )

    def run_dir(self, run_id: str) -> Path:
        """Public: return the on-disk directory for ``run_id``.

        Raises :class:`ValueError` if the id is malformed. The directory
        is not created by this call; use :meth:`init_run` for that.
        """
        self._validate_run_id(run_id)
        return self.runs_dir / run_id

    # Kept as an internal alias for legacy callers; prefer ``run_dir``.
    _run_dir = run_dir

    def get_artifact_dir(self, run_id: str) -> Path:
        run_dir = self.run_dir(run_id)
        artifact_dir = run_dir / "artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        return artifact_dir

    def init_run(self, run_id: str) -> RunState:
        run_dir = self._run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "artifacts").mkdir(exist_ok=True)
        (run_dir / "logs").mkdir(exist_ok=True)
        state = RunState(run_id=run_id)
        self.save(state)
        return state

    def save(self, state: RunState) -> None:
        run_dir = self._run_dir(state.run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        state.touch()
        target = run_dir / "state.json"
        fd, tmp_path = tempfile.mkstemp(
            dir=run_dir, prefix=".state-", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(state.model_dump_json(indent=2))
            os.replace(tmp_path, target)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def load(self, run_id: str) -> RunState | None:
        try:
            path = self._run_dir(run_id) / "state.json"
        except ValueError:
            _log.warning("Attempted to load run with invalid id: %s", run_id)
            return None
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return RunState.model_validate(data)
        except (json.JSONDecodeError, ValueError) as exc:
            _log.error("Run state %s is corrupted: %s", run_id, exc)
            raise CorruptedStateError(run_id, str(path)) from exc

    def list_runs(self) -> list[str]:
        return sorted(
            [d.name for d in self.runs_dir.iterdir() if d.is_dir() and (d / "state.json").exists()]
        )

    def write_artifact(self, run_id: str, filename: str, content: Any) -> Path:
        artifact_dir = self.get_artifact_dir(run_id)
        path = artifact_dir / filename
        if isinstance(content, (dict, list)):
            with open(path, "w", encoding="utf-8") as f:
                json.dump(content, f, indent=2, ensure_ascii=False)
        else:
            with open(path, "w", encoding="utf-8") as f:
                f.write(str(content))
        return path

    def append_log(self, run_id: str, entry: dict[str, Any]) -> None:
        run_dir = self._run_dir(run_id)
        log_dir = run_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "workflow.jsonl"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # -- Job helpers for detached workers --

    def job_dir(self, run_id: str, step: str) -> Path:
        """Return the job directory for a given run+step combination."""
        rd = self.run_dir(run_id)
        return rd / "jobs" / step

    def job_pid_file(self, run_id: str, step: str) -> Path:
        return self.job_dir(run_id, step) / "pid"

    def job_events_file(self, run_id: str, step: str) -> Path:
        return self.job_dir(run_id, step) / "events.jsonl"

    def job_cmd_file(self, run_id: str, step: str) -> Path:
        return self.job_dir(run_id, step) / "cmd.jsonl"

    def job_status_file(self, run_id: str, step: str) -> Path:
        return self.job_dir(run_id, step) / "status"

    def ensure_job_dir(self, run_id: str, step: str) -> Path:
        """Create and return the job directory."""
        jd = self.job_dir(run_id, step)
        jd.mkdir(parents=True, exist_ok=True)
        return jd


class CorruptedStateError(Exception):
    """Raised when a state.json file exists but cannot be parsed."""

    def __init__(self, run_id: str, path: str) -> None:
        self.run_id = run_id
        self.path = path
        super().__init__(f"Run state for '{run_id}' is corrupted: {path}")
