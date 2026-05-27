# aptgent/aptgent/jobs/events.py
"""Event protocol for detached worker communication.

All events are written as one JSON object per line to an events.jsonl file.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from aptgent.protocol.line_json import JsonlEmitter, iter_jsonl


def _now_ts() -> str:
    return datetime.now(timezone.utc).isoformat()


class EventWriter:
    """Append-only writer for job events."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(path, "a", encoding="utf-8")
        self._emitter = JsonlEmitter(self._file)
        self._lock = threading.Lock()

    def _write(self, obj: dict[str, Any]) -> None:
        with self._lock:
            self._emitter.emit(obj)

    def write_started(self, *, pid: int, extra: dict[str, Any] | None = None) -> None:
        evt: dict[str, Any] = {"type": "started", "ts": _now_ts(), "pid": pid}
        if extra:
            evt["extra"] = extra
        self._write(evt)

    def write_progress(self, *, done: int, total: int, extra: dict[str, Any] | None = None) -> None:
        evt: dict[str, Any] = {"type": "progress", "ts": _now_ts(), "done": done, "total": total}
        if extra:
            evt["extra"] = extra
        self._write(evt)

    def write_hit(self, *, candidate_id: str, probability: float, extra: dict[str, Any] | None = None) -> None:
        evt: dict[str, Any] = {
            "type": "hit",
            "ts": _now_ts(),
            "candidate_id": candidate_id,
            "probability": probability,
        }
        if extra:
            evt["extra"] = extra
        self._write(evt)

    def write_done(self, *, summary: dict[str, Any] | None = None) -> None:
        evt: dict[str, Any] = {"type": "done", "ts": _now_ts()}
        if summary:
            evt["summary"] = summary
        self._write(evt)

    def write_error(self, *, message: str) -> None:
        self._write({"type": "error", "ts": _now_ts(), "message": message})

    def write_heartbeat(self) -> None:
        self._write({"type": "heartbeat", "ts": _now_ts(), "alive": True})

    def close(self) -> None:
        self._file.close()


class EventReader:
    """Read events from an events.jsonl file."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def iter_events(self) -> Iterator[dict[str, Any]]:
        if not self._path.exists():
            return
        with open(self._path, "r", encoding="utf-8") as f:
            yield from iter_jsonl(f)

    def iter_events_from(self, start_offset: int) -> Iterator[dict[str, Any]]:
        """Yield events starting from byte offset *start_offset*."""
        if not self._path.exists():
            return
        with open(self._path, "r", encoding="utf-8") as f:
            f.seek(start_offset)
            yield from iter_jsonl(f)

    def file_size(self) -> int:
        if not self._path.exists():
            return 0
        return self._path.stat().st_size


def read_last_event(path: Path) -> dict[str, Any] | None:
    """Read the last complete event from a JSONL file.

    Avoids reading the entire file by seeking near the end and scanning
    backwards for the last complete JSONL line.
    """
    if not path.exists():
        return None
    size = path.stat().st_size
    if size == 0:
        return None
    try:
        chunk_size = min(size, 4096)
        with open(path, "r", encoding="utf-8") as f:
            f.seek(size - chunk_size)
            text = f.read()
        lines = text.split("\n")
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                return json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
        return None
    except OSError:
        return None
