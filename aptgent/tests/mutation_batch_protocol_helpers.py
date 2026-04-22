from __future__ import annotations

import json
import queue
import threading
from unittest.mock import MagicMock


class LineReader:
    """File-like object backed by a queue for line-by-line pipe simulation."""

    def __init__(self) -> None:
        self._q: queue.Queue[str | None] = queue.Queue()

    def put_line(self, line: str) -> None:
        self._q.put(line)

    def close(self) -> None:
        self._q.put(None)

    def __iter__(self):
        return self

    def __next__(self) -> str:
        item = self._q.get()
        if item is None:
            raise StopIteration
        return item


class FakePopen:
    """Stub subprocess.Popen that simulates the mutation-batch line-JSON protocol."""

    def __init__(self, cmd, **kwargs) -> None:
        self.stdout = LineReader()
        self.stderr = LineReader()
        self.stdin = MagicMock()
        self.returncode = 0
        self._cmd = cmd
        self._lines = [
            json.dumps(
                {
                    "type": "ready",
                    "model_order": ["m1.pkl", "m2.pkl"],
                    "device": "cpu",
                }
            ),
            json.dumps({"type": "progress", "done": 100, "total": 256}),
            json.dumps(
                {
                    "type": "hit",
                    "sequence": "ATGCTAGC",
                    "mean_probability": 0.95,
                    "model_probabilities": [0.92, 0.98],
                }
            ),
            json.dumps({"type": "progress", "done": 256, "total": 256}),
            json.dumps({"type": "done", "total": 256, "hits": 1}),
        ]

    def feed_lines(self) -> None:
        for line in self._lines:
            self.stdout.put_line(line)
        self.stdout.close()
        self.stderr.close()

    def wait(self, timeout=None) -> int:
        return self.returncode


class FakePopenFactory:
    def __init__(self, popen_class=None) -> None:
        self._popen_class = popen_class or FakePopen
        self.proc = None

    def __call__(self, cmd, **kwargs):
        self.proc = self._popen_class(cmd, **kwargs)
        timer = threading.Timer(0.05, self.proc.feed_lines)
        timer.daemon = True
        timer.start()
        return self.proc
