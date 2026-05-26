"""Line-delimited JSON protocol helpers."""

from __future__ import annotations

import json
from typing import Any, Callable, IO, Iterator


class JsonlEmitter:
    """Write one JSON object per line to a text stream, with immediate flush."""

    def __init__(self, stream: IO[str]) -> None:
        self._stream = stream

    def emit(self, obj: dict[str, Any]) -> None:
        self._stream.write(json.dumps(obj, ensure_ascii=False) + "\n")
        self._stream.flush()


def iter_jsonl(
    reader: IO[str],
    *,
    on_malformed: Callable[[str, Exception], None] | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield parsed JSON objects from a line-delimited text reader.

    Blank lines are skipped.  Malformed lines are also skipped; if
    *on_malformed* is provided it is called with the raw line and the
    exception so the caller can log or collect diagnostics.
    """
    for raw in reader:
        line = raw.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError as exc:
            if on_malformed is not None:
                on_malformed(line, exc)
