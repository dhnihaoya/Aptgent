from __future__ import annotations

import pytest

from aptgent.adapters.rnacomposer import HttpResponse, RNAComposerAdapter


_PDB_SAMPLE = (
    "HEADER  RNAComposer model\n"
    "ATOM      1  P     A A   1      10.000  10.000  10.000  1.00  0.00           P\n"
    "ATOM      2  C1'   A A   1      10.500  10.500  10.500  1.00  0.00           C\n"
    "ATOM      3  P     U A   2      11.000  11.000  11.000  1.00  0.00           P\n"
    "END\n"
)


def _make_transport(response: HttpResponse):
    calls: list[tuple[str, dict, dict]] = []

    def transport(url, data=None, headers=None):
        calls.append((url, dict(data or {}), dict(headers or {})))
        return response

    return transport, calls


def test_submit_returns_completed_when_response_contains_pdb():
    response = HttpResponse(
        status=200,
        url="https://rnacomposer.cs.put.poznan.pl/Home/computing",
        headers={"content-type": "chemical/x-pdb"},
        body=_PDB_SAMPLE.encode("utf-8"),
    )
    transport, calls = _make_transport(response)
    adapter = RNAComposerAdapter(transport=transport)

    job = adapter.submit("ACGUACGU", "((....))")
    assert job.status == "completed"
    assert job.job_id
    assert calls[0][1]["sequence"] == "ACGUACGU"


def test_fetch_writes_pdb_to_output_dir(tmp_path):
    response = HttpResponse(
        status=200,
        url="https://rnacomposer.cs.put.poznan.pl/Home/computing",
        headers={"content-type": "chemical/x-pdb"},
        body=_PDB_SAMPLE.encode("utf-8"),
    )
    transport, _ = _make_transport(response)
    adapter = RNAComposerAdapter(transport=transport)

    job = adapter.submit("ACGU", "....")
    out_path = adapter.fetch(job.job_id, tmp_path)
    contents = open(out_path, encoding="utf-8").read()
    assert "ATOM" in contents
    assert out_path.startswith(str(tmp_path))


def test_submit_raises_on_http_error():
    response = HttpResponse(status=500, url="https://example", body=b"oops")
    transport, _ = _make_transport(response)
    adapter = RNAComposerAdapter(transport=transport)
    with pytest.raises(RuntimeError):
        adapter.submit("ACGU", "....")


def test_predict_to_path_convenience_writes_pdb(tmp_path):
    response = HttpResponse(
        status=200,
        url="https://rnacomposer.cs.put.poznan.pl/jobs/foo",
        headers={"content-type": "text/plain"},
        body=_PDB_SAMPLE.encode("utf-8"),
    )
    transport, _ = _make_transport(response)
    adapter = RNAComposerAdapter(transport=transport)
    path = adapter.predict_to_path("ACGU", "....", tmp_path, candidate_id="cand_0")
    assert "ATOM" in open(path, encoding="utf-8").read()


def test_poll_returns_unknown_for_unknown_job():
    adapter = RNAComposerAdapter(transport=lambda *args, **kwargs: HttpResponse(200, "url"))
    job = adapter.poll("ghost-id")
    assert job.status == "unknown"
