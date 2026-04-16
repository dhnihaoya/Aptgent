from __future__ import annotations

import subprocess
import urllib.error

from aptgent.adapters.pdb_analysis import PdbAnalysisAdapter


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


def test_fetch_falls_back_to_urllib_when_wget_fails(tmp_path, monkeypatch):
    adapter = PdbAnalysisAdapter()

    monkeypatch.setattr("aptgent.adapters.pdb_analysis.shutil.which", lambda command: "/usr/bin/wget")

    def fake_run(*args, **kwargs):
        raise subprocess.CalledProcessError(
            1,
            args[0],
            stderr="proxy error",
        )

    monkeypatch.setattr("aptgent.adapters.pdb_analysis.subprocess.run", fake_run)
    monkeypatch.setattr(
        "aptgent.adapters.pdb_analysis.urllib.request.urlopen",
        lambda url, timeout=30: _FakeResponse(b"ATOM\n"),
    )

    path = adapter.fetch("1ehz", tmp_path)

    assert path.name == "1EHZ.pdb"
    assert path.read_bytes() == b"ATOM\n"


def test_fetch_reports_both_wget_and_urllib_failures(tmp_path, monkeypatch):
    adapter = PdbAnalysisAdapter()

    monkeypatch.setattr("aptgent.adapters.pdb_analysis.shutil.which", lambda command: "/usr/bin/wget")

    def fake_run(*args, **kwargs):
        raise subprocess.CalledProcessError(
            1,
            args[0],
            stderr="proxy error",
        )

    monkeypatch.setattr("aptgent.adapters.pdb_analysis.subprocess.run", fake_run)

    def fake_urlopen(url, timeout=30):
        raise urllib.error.URLError("dns failure")

    monkeypatch.setattr("aptgent.adapters.pdb_analysis.urllib.request.urlopen", fake_urlopen)

    try:
        adapter.fetch("1ehz", tmp_path)
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("Expected adapter.fetch() to fail when both download methods fail.")

    assert "wget failed while downloading 1EHZ" in message
    assert "urllib fallback failed while downloading 1EHZ" in message
