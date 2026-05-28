# aptgent/aptgent/jobs/resume.py
"""Resume detection utilities for job runners.

Provides building blocks for the common "read an existing JSONL artifact,
validate its header, and iterate completed entries" pattern shared by
``_run_enumeration``, ``_run_specificity``, and ``_run_docking``.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Iterator

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# JSONL header validation
# ---------------------------------------------------------------------------

def read_jsonl_header(
    path: Path,
) -> dict[str, Any] | None:
    """Read the first line of *path* as JSON and return it.

    Returns ``None`` when the file does not exist, is empty, or the first
    line cannot be parsed.
    """
    if not path.exists() or path.stat().st_size == 0:
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            first_line = f.readline().strip()
        if not first_line:
            return None
        return json.loads(first_line)
    except (OSError, json.JSONDecodeError):
        return None


def validate_meta(
    path: Path,
    expected_meta: dict[str, Any],
) -> bool:
    """Return ``True`` if the artifact header ``meta`` matches *expected_meta*.

    Returns ``False`` if the file is missing, empty, has no ``meta`` key, or
    the meta differs.
    """
    header = read_jsonl_header(path)
    if header is None:
        return False
    stored = header.get("meta")
    return stored == expected_meta


# ---------------------------------------------------------------------------
# JSONL line iteration (skip header)
# ---------------------------------------------------------------------------

def iter_result_lines(
    path: Path,
) -> Iterator[dict[str, Any]]:
    """Yield parsed JSON objects from *path*, skipping the first (header) line.

    Malformed lines are silently ignored.
    """
    if not path.exists() or path.stat().st_size == 0:
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            _header = f.readline()  # skip header
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return


# ---------------------------------------------------------------------------
# Artifact file management
# ---------------------------------------------------------------------------

def open_artifact(
    path: Path,
    meta: dict[str, Any] | None = None,
) -> tuple[Any, bool]:
    """Open a JSONL artifact for appending or fresh writing.

    If *path* already exists and is non-empty, opens it in append mode and
    returns ``(file_handle, False)``.  Otherwise creates the file, writes
    *meta* as the header line (if provided), and returns
    ``(file_handle, True)``.

    The caller is responsible for closing the file handle.
    """
    is_fresh = False
    if path.exists() and path.stat().st_size > 0:
        fh = open(path, "a", encoding="utf-8")  # noqa: SIM115
    else:
        fh = open(path, "w", encoding="utf-8")  # noqa: SIM115
        is_fresh = True
        if meta is not None:
            fh.write(json.dumps({"meta": meta}, ensure_ascii=False) + "\n")
            fh.flush()
    return fh, is_fresh
