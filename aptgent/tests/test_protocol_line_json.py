"""Tests for aptgent.protocol.line_json — JsonlEmitter and iter_jsonl."""
from __future__ import annotations

import io

from aptgent.protocol.line_json import JsonlEmitter, iter_jsonl


def test_emitter_writes_newline_delimited_json():
    buf = io.StringIO()
    emitter = JsonlEmitter(buf)
    emitter.emit({"type": "ready", "n": 1})
    emitter.emit({"type": "done"})
    lines = buf.getvalue().strip().split("\n")
    assert len(lines) == 2
    assert '"type": "ready"' in lines[0]
    assert '"type": "done"' in lines[1]


def test_emitter_flushes_after_each_emit():
    """Ensure flush() is called so downstream readers see data immediately."""
    flushed = []

    class TrackingIO(io.StringIO):
        def flush(self):
            super().flush()
            flushed.append(True)

    buf = TrackingIO()
    emitter = JsonlEmitter(buf)
    emitter.emit({"a": 1})
    assert len(flushed) == 1
    emitter.emit({"b": 2})
    assert len(flushed) == 2


def test_iter_jsonl_skips_blank_lines():
    text = '\n{"a":1}\n\n{"b":2}\n\n'
    reader = io.StringIO(text)
    items = list(iter_jsonl(reader))
    assert items == [{"a": 1}, {"b": 2}]


def test_iter_jsonl_skips_malformed_lines():
    text = '{"a":1}\nNOT JSON\n{"b":2}\n'
    reader = io.StringIO(text)
    items = list(iter_jsonl(reader))
    assert items == [{"a": 1}, {"b": 2}]


def test_iter_jsonl_on_malformed_callback():
    text = '{"ok":1}\nBAD\n'
    reader = io.StringIO(text)
    errors: list[tuple[str, Exception]] = []
    items = list(iter_jsonl(reader, on_malformed=lambda line, exc: errors.append((line, exc))))
    assert items == [{"ok": 1}]
    assert len(errors) == 1
    assert errors[0][0] == "BAD"


def test_iter_jsonl_empty_input():
    reader = io.StringIO("")
    assert list(iter_jsonl(reader)) == []


def test_emitter_handles_unicode():
    buf = io.StringIO()
    emitter = JsonlEmitter(buf)
    emitter.emit({"msg": "你好世界"})
    line = buf.getvalue().strip()
    assert "你好世界" in line
