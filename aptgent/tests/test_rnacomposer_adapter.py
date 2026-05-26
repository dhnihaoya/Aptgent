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

_COMPOSE_FORM = b"""
<form id="composeForm" action="/;jsessionid=test-session" method="post">
  <textarea id="input" name="content"></textarea>
  <input id="predict2d" name="addPredict2dTool" type="checkbox" value="true">
  <input type="hidden" name="_addPredict2dTool" value="on">
  <select id="predict2dTool" name="predict2dTool"></select>
  <input class="button" name="send" id="send" value="Compose" type="submit">
</form>
"""

_PROGRESS_PAGE = b"""
<form id="progressForm" action="task/progress" method="post">
  <input type="hidden" name="taskID" value="task-123">
</form>
<form id="resultsForm" action="task/result" method="post">
  <input type="hidden" name="taskID" value="task-123">
</form>
"""

_FINISHED_PROGRESS = b"""
<input type="hidden" id="processingFinished" name="processingFinished" value="true">
"""

_RESULT_PAGE = b"""
<a href="/Home/GetResult?resId=result-123&amp;name=aptgent.pdb">aptgent.pdb</a>
"""


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
    assert calls[1][1]["content"] == ">aptgent\nACGUACGU\n((....))"


def test_submit_uses_current_interactive_form_protocol():
    calls: list[tuple[str, dict, dict]] = []

    def transport(url, data=None, headers=None):
        calls.append((url, dict(data or {}), dict(headers or {})))
        if data is None:
            return HttpResponse(
                status=200,
                url="https://rnacomposer.cs.put.poznan.pl/",
                body=_COMPOSE_FORM,
            )
        if url == "https://rnacomposer.cs.put.poznan.pl/;jsessionid=test-session":
            return HttpResponse(
                status=200,
                url=url,
                body=_PROGRESS_PAGE,
            )
        return HttpResponse(status=404, url=url, body=b"not found")

    adapter = RNAComposerAdapter(transport=transport)

    job = adapter.submit("ACGUACGU", "")

    assert job.status == "queued"
    assert job.job_id == "task-123"
    assert calls[0][0] == "https://rnacomposer.cs.put.poznan.pl/"
    assert calls[1][0] == "https://rnacomposer.cs.put.poznan.pl/;jsessionid=test-session"
    assert calls[1][1]["content"] == ">aptgent\nACGUACGU\nRNAfold"
    assert "sequence" not in calls[1][1]


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


def test_fetch_downloads_pdb_from_current_result_page(tmp_path):
    calls: list[tuple[str, dict, dict]] = []

    def transport(url, data=None, headers=None):
        calls.append((url, dict(data or {}), dict(headers or {})))
        if data is None and url == "https://rnacomposer.cs.put.poznan.pl/":
            return HttpResponse(status=200, url=url, body=_COMPOSE_FORM)
        if url == "https://rnacomposer.cs.put.poznan.pl/;jsessionid=test-session":
            return HttpResponse(status=200, url=url, body=_PROGRESS_PAGE)
        if url == "https://rnacomposer.cs.put.poznan.pl/task/progress":
            return HttpResponse(status=200, url=url, body=_FINISHED_PROGRESS)
        if url == "https://rnacomposer.cs.put.poznan.pl/task/result":
            return HttpResponse(status=200, url=url, body=_RESULT_PAGE)
        if url == "https://rnacomposer.cs.put.poznan.pl/Home/GetResult?resId=result-123&name=aptgent.pdb":
            return HttpResponse(
                status=200,
                url=url,
                headers={"content-type": "chemical/x-pdb"},
                body=_PDB_SAMPLE.encode("utf-8"),
            )
        return HttpResponse(status=404, url=url, body=b"not found")

    adapter = RNAComposerAdapter(
        transport=transport,
        max_poll_seconds=1,
        poll_interval_seconds=0,
    )

    job = adapter.submit("ACGU", "")
    out_path = adapter.fetch(job.job_id, tmp_path)

    assert "ATOM" in open(out_path, encoding="utf-8").read()
    assert any(call[0].endswith("/task/progress") for call in calls)
    assert any("/Home/GetResult" in call[0] for call in calls)


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
