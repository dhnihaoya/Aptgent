"""RNAComposer scraping adapter for tertiary structure prediction.

RNAComposer (https://rnacomposer.cs.put.poznan.pl/) does NOT expose a
documented REST API. The interactive mode is a JSF web form that returns a
PDB file; the batch mode requires a registered account and returns results
to a user workspace. This adapter implements an HTTP scraper that is good
enough for the common case (interactive mode, single sequence) and is
designed so the transport layer is injectable for tests.

Behavioral notes
================
- ``submit(sequence, secondary_structure)`` returns a ``TertiaryStructureJob``
  with ``status="queued"`` (or ``"completed"`` if RNAComposer answered the
  POST synchronously, which is the common case for short aptamers).
- ``poll(job_id)`` re-fetches the result page; transitions to
  ``"completed"`` once a PDB file URL is found.
- ``fetch(job_id, output_dir)`` downloads the PDB into the target directory
  and returns its path.

If anything fails (network, parse, RNAComposer returning an error page) the
adapter raises ``RuntimeError`` with a clear message that the TUI shows to
the user; they can then fall back to manual upload mode.
"""
from __future__ import annotations

import html
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from aptgent.adapters.structure_services import TertiaryStructureJob

_DEFAULT_BASE_URL = "https://rnacomposer.cs.put.poznan.pl"
_INTERACTIVE_PATH = "/"
_DEFAULT_TASK_NAME = "aptgent"
_DEFAULT_2D_TOOL = "RNAfold"


HttpTransport = Callable[[str, dict[str, Any] | None, dict[str, str] | None], "HttpResponse"]
_OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())


@dataclass
class HttpResponse:
    """Minimal HTTP response surface so tests can mock the transport."""

    status: int
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""

    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


def _default_transport(
    url: str,
    data: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> HttpResponse:
    """Default urllib-based transport. Replaced in tests."""
    encoded = None
    if data is not None:
        encoded = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=encoded,
        headers=headers or {"User-Agent": "Aptgent/1.0 (RNAComposer client)"},
        method="POST" if data is not None else "GET",
    )
    with _OPENER.open(req, timeout=60) as resp:
        body = resp.read()
        return HttpResponse(
            status=resp.status,
            url=resp.url,
            headers={k.lower(): v for k, v in resp.headers.items()},
            body=body,
        )


class RNAComposerAdapter:
    """HTTP scraper for the RNAComposer interactive mode."""

    def __init__(
        self,
        *,
        base_url: str = _DEFAULT_BASE_URL,
        interactive_path: str = _INTERACTIVE_PATH,
        timeout_seconds: int = 60,
        max_poll_seconds: int = 1800,
        poll_interval_seconds: int = 15,
        transport: HttpTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.interactive_path = interactive_path
        self.timeout_seconds = timeout_seconds
        self.max_poll_seconds = max_poll_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self._transport: HttpTransport = transport or _default_transport
        # job_id -> raw response info (HTML / PDB) cached after submit so
        # poll() and fetch() don't need to refetch synchronously.
        self._cache: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Protocol API
    # ------------------------------------------------------------------

    def submit(self, sequence: str, secondary_structure: str) -> TertiaryStructureJob:
        if not sequence:
            raise ValueError("RNAComposer submit requires a non-empty sequence")

        url = f"{self.base_url}{self.interactive_path}"
        try:
            form_response = self._transport(url, None, _default_headers())
            if form_response.status >= 400:
                raise RuntimeError(f"RNAComposer form returned HTTP {form_response.status}")

            form_text = form_response.text()
            submit_url = _extract_compose_action(form_text, form_response.url) or url
            response = self._transport(
                submit_url,
                _build_submit_payload(sequence, secondary_structure),
                _default_headers(referer=form_response.url),
            )
        except Exception as exc:
            raise RuntimeError(
                f"RNAComposer submit failed: {exc}. Consider switching to "
                "manual structure upload."
            ) from exc

        if response.status >= 400:
            raise RuntimeError(
                f"RNAComposer submit returned HTTP {response.status} for "
                f"sequence of length {len(sequence)}."
            )

        body_text = response.text()
        pdb_text = _maybe_extract_pdb_from_response(body_text, response.headers)
        job_id = _extract_task_id(body_text) or _extract_job_id(body_text, response.url)
        status = "completed" if pdb_text else "queued"
        if not job_id:
            job_id = f"interactive_{int(time.time() * 1000)}"

        self._cache[job_id] = {
            "sequence": sequence,
            "secondary_structure": secondary_structure,
            "body": body_text,
            "headers": response.headers,
            "pdb_text": pdb_text,
            "status": status,
            "status_url": _extract_form_action(body_text, "progressForm", response.url)
            or urllib.parse.urljoin(response.url, "task/progress"),
            "result_url": _extract_form_action(body_text, "resultsForm", response.url)
            or urllib.parse.urljoin(response.url, "task/result"),
            "submitted_at": time.time(),
        }
        return TertiaryStructureJob(
            provider="rnacomposer",
            status=status,
            job_id=job_id,
            metadata={"sequence_length": str(len(sequence))},
        )

    def poll(self, job_id: str) -> TertiaryStructureJob:
        entry = self._cache.get(job_id)
        if entry is None:
            return TertiaryStructureJob(
                provider="rnacomposer",
                status="unknown",
                job_id=job_id,
                note="Unknown RNAComposer job id (no cached state).",
            )

        if entry.get("status") == "completed" and entry.get("pdb_text"):
            return TertiaryStructureJob(
                provider="rnacomposer",
                status="completed",
                job_id=job_id,
            )

        url = entry.get("status_url") or urllib.parse.urljoin(self.base_url + "/", "task/progress")
        try:
            response = self._transport(
                url,
                {"taskID": job_id},
                _default_headers(referer=self.base_url + "/"),
            )
        except Exception as exc:
            return TertiaryStructureJob(
                provider="rnacomposer",
                status="pending",
                job_id=job_id,
                note=f"Poll failed: {exc}",
            )

        body_text = response.text()
        pdb_text = _maybe_extract_pdb_from_response(body_text, response.headers)
        if pdb_text:
            entry["pdb_text"] = pdb_text
            entry["status"] = "completed"
            return TertiaryStructureJob(
                provider="rnacomposer",
                status="completed",
                job_id=job_id,
            )

        if _processing_finished(body_text):
            result_url = entry.get("result_url") or urllib.parse.urljoin(self.base_url + "/", "task/result")
            try:
                result_response = self._transport(
                    result_url,
                    {"taskID": job_id},
                    _default_headers(referer=self.base_url + "/"),
                )
                result_text = result_response.text()
                pdb_text = _maybe_extract_pdb_from_response(
                    result_text,
                    result_response.headers,
                )
                if not pdb_text:
                    pdb_url = _extract_pdb_download_url(result_text, result_response.url)
                    if pdb_url:
                        pdb_response = self._transport(
                            pdb_url,
                            None,
                            _default_headers(referer=result_response.url),
                        )
                        pdb_text = _maybe_extract_pdb_from_response(
                            pdb_response.text(),
                            pdb_response.headers,
                        )
                if pdb_text:
                    entry["pdb_text"] = pdb_text
                    entry["status"] = "completed"
                    return TertiaryStructureJob(
                        provider="rnacomposer",
                        status="completed",
                        job_id=job_id,
                    )
            except Exception as exc:
                return TertiaryStructureJob(
                    provider="rnacomposer",
                    status="pending",
                    job_id=job_id,
                    note=f"Result fetch failed: {exc}",
                )

        # Heuristic: detect explicit failure language
        if _looks_like_failure_page(body_text):
            entry["status"] = "failed"
            return TertiaryStructureJob(
                provider="rnacomposer",
                status="failed",
                job_id=job_id,
                note="RNAComposer reported a failure on the status page.",
            )

        return TertiaryStructureJob(
            provider="rnacomposer",
            status="pending",
            job_id=job_id,
        )

    def fetch(self, job_id: str, output_dir: str | Path) -> str:
        entry = self._cache.get(job_id)
        if entry is None:
            raise RuntimeError(f"Cannot fetch unknown RNAComposer job id: {job_id}")

        if not entry.get("pdb_text"):
            deadline = time.monotonic() + self.max_poll_seconds
            while time.monotonic() < deadline and entry.get("status") != "completed":
                self.poll(job_id)
                if entry.get("status") == "completed":
                    break
                time.sleep(self.poll_interval_seconds)

        pdb_text = entry.get("pdb_text")
        if not pdb_text:
            raise RuntimeError(
                f"RNAComposer job {job_id} did not produce a PDB within "
                f"{self.max_poll_seconds}s."
            )

        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{job_id}.pdb"
        out_path.write_text(pdb_text, encoding="utf-8")
        return str(out_path)

    # ------------------------------------------------------------------
    # Convenience: end-to-end run helper
    # ------------------------------------------------------------------

    def predict_to_path(
        self,
        sequence: str,
        secondary_structure: str,
        output_dir: str | Path,
        *,
        candidate_id: str | None = None,
    ) -> str:
        """Convenience: submit + wait + fetch in one call."""
        job = self.submit(sequence, secondary_structure)
        if job.status == "failed":
            raise RuntimeError(f"RNAComposer rejected submission: {job.note}")
        if candidate_id:
            entry = self._cache.get(job.job_id or "")
            if entry is not None:
                entry["candidate_id"] = candidate_id
        return self.fetch(job.job_id or "", output_dir)


# ---------------------------------------------------------------------------
# Response parsing helpers (deliberately permissive)
# ---------------------------------------------------------------------------


def _default_headers(*, referer: str | None = None) -> dict[str, str]:
    headers = {"User-Agent": "Aptgent/1.0 (RNAComposer client)"}
    if referer:
        headers["Referer"] = referer
    return headers


def _build_submit_payload(
    sequence: str,
    secondary_structure: str,
    *,
    task_name: str = _DEFAULT_TASK_NAME,
) -> dict[str, str]:
    secondary = secondary_structure.strip() or _DEFAULT_2D_TOOL
    payload = {
        "content": f">{task_name}\n{sequence}\n{secondary}",
        "_addPredict2dTool": "on",
        "send": "Compose",
        "_sendEmail": "on",
        "email": "",
    }
    if not secondary_structure.strip():
        payload["addPredict2dTool"] = "true"
        payload["predict2dTool"] = _DEFAULT_2D_TOOL.lower()
    return payload


_PDB_LINE_RE = re.compile(r"^(?:ATOM|HETATM)\s", re.MULTILINE)


def _maybe_extract_pdb_from_response(
    body_text: str,
    headers: dict[str, str] | None = None,
) -> str | None:
    """Return PDB text if *body_text* looks like a PDB, else None."""
    headers = headers or {}
    content_type = headers.get("content-type", "").lower()
    if "chemical/x-pdb" in content_type or content_type.startswith("text/plain"):
        if _PDB_LINE_RE.search(body_text):
            return body_text
    if _PDB_LINE_RE.search(body_text) and len(body_text) > 200:
        # Heuristic: any HTML wrapping a PDB will still have ATOM lines
        # surrounded by non-PDB content, but for the common interactive
        # response the body IS the PDB.
        if not body_text.lstrip().startswith("<"):
            return body_text
    return None


_JOB_ID_HINT_RE = re.compile(r"(?:jobId|task|job)[=/]([A-Za-z0-9_\-]+)")
_COMPOSE_FORM_RE = re.compile(
    r"<form[^>]+id=[\"']composeForm[\"'][^>]+action=[\"']([^\"']+)",
    re.IGNORECASE,
)
_FORM_ACTION_RE = re.compile(
    r"<form[^>]+id=[\"'](?P<form_id>[^\"']+)[\"'][^>]+action=[\"'](?P<action>[^\"']+)",
    re.IGNORECASE,
)
_TASK_ID_RE = re.compile(
    r"name=[\"']taskID[\"'][^>]+value=[\"']([^\"']+)",
    re.IGNORECASE,
)
_PROCESSING_FINISHED_RE = re.compile(
    r"name=[\"']processingFinished[\"'][^>]+value=[\"']true[\"']",
    re.IGNORECASE,
)
_PDB_DOWNLOAD_RE = re.compile(r"href=[\"']([^\"']*/Home/GetResult\?[^\"']+)", re.IGNORECASE)


def _extract_compose_action(body_text: str, page_url: str) -> str | None:
    match = _COMPOSE_FORM_RE.search(body_text)
    if not match:
        return None
    return urllib.parse.urljoin(page_url, match.group(1))


def _extract_form_action(body_text: str, form_id: str, page_url: str) -> str | None:
    for match in _FORM_ACTION_RE.finditer(body_text):
        if match.group("form_id") == form_id:
            return urllib.parse.urljoin(page_url, match.group("action"))
    return None


def _extract_task_id(body_text: str) -> str | None:
    match = _TASK_ID_RE.search(body_text)
    if match:
        return match.group(1)
    return None


def _processing_finished(body_text: str) -> bool:
    return bool(_PROCESSING_FINISHED_RE.search(body_text))


def _extract_pdb_download_url(body_text: str, page_url: str) -> str | None:
    match = _PDB_DOWNLOAD_RE.search(body_text)
    if not match:
        return None
    return urllib.parse.urljoin(page_url, html.unescape(match.group(1)))


def _extract_job_id(body_text: str, url: str) -> str | None:
    match = _JOB_ID_HINT_RE.search(url)
    if match:
        return match.group(1)
    match = _JOB_ID_HINT_RE.search(body_text)
    if match:
        return match.group(1)
    return None


_FAILURE_RE = re.compile(r"(error|failure|rejected|invalid)", re.IGNORECASE)


def _looks_like_failure_page(body_text: str) -> bool:
    if "<html" in body_text.lower() and _FAILURE_RE.search(body_text):
        return True
    return False


