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

import dataclasses
import logging
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from aptgent.adapters.structure_services import TertiaryStructureJob

_log = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://rnacomposer.cs.put.poznan.pl"
_INTERACTIVE_PATH = "/Home/computing"


HttpTransport = Callable[[str, dict[str, Any] | None, dict[str, str] | None], "HttpResponse"]


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
    with urllib.request.urlopen(req, timeout=60) as resp:
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

        payload = {
            "sequence": sequence,
            "secondaryStructure": secondary_structure or "",
        }
        url = f"{self.base_url}{self.interactive_path}"
        try:
            response = self._transport(
                url,
                payload,
                {"User-Agent": "Aptgent/1.0 (RNAComposer client)"},
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
        job_id = _extract_job_id(body_text, response.url)
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

        url = entry.get("status_url") or f"{self.base_url}/jobs/{job_id}"
        try:
            response = self._transport(url, None, None)
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


def dataclass_to_dict(value: Any) -> dict[str, Any]:
    """Pickleable conversion helper used by job-runner serialization."""
    if dataclasses.is_dataclass(value):
        return dataclasses.asdict(value)
    return dict(value)
