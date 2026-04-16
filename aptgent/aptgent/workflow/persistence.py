from __future__ import annotations

import json
import logging
import re
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

    def _run_dir(self, run_id: str) -> Path:
        self._validate_run_id(run_id)
        return self.runs_dir / run_id

    def get_artifact_dir(self, run_id: str) -> Path:
        run_dir = self._run_dir(run_id)
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
        with open(run_dir / "state.json", "w", encoding="utf-8") as f:
            f.write(state.model_dump_json(indent=2))

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
        except Exception:
            _log.exception("Failed to load run state from %s", path)
            return None

    def list_runs(self) -> list[str]:
        return sorted(
            [d.name for d in self.runs_dir.iterdir() if d.is_dir() and (d / "state.json").exists()]
        )

    def write_artifact(self, run_id: str, filename: str, content: Any, mime_type: str = "application/json") -> Path:
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
