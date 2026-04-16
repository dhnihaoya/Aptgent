from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class StructureMatch:
    structure_id: str
    provider: str = "pdb"
    description: str = ""
    download_url: str | None = None


@dataclass(frozen=True)
class StructureLookupResult:
    status: str = "not_configured"
    matches: tuple[StructureMatch, ...] = ()
    note: str = ""


class StructureLookupAdapter(Protocol):
    def lookup(self, sequence: str) -> StructureLookupResult: ...


class StructureFetchAdapter(Protocol):
    def fetch(self, match: StructureMatch, output_dir: str | Path) -> str: ...


@dataclass(frozen=True)
class TertiaryStructureJob:
    provider: str = "rnacomposer"
    status: str = "pending"
    job_id: str | None = None
    result_path: str | None = None
    note: str = ""
    metadata: dict[str, str] = field(default_factory=dict)


class TertiaryStructureAdapter(Protocol):
    def submit(self, sequence: str, secondary_structure: str) -> TertiaryStructureJob: ...

    def poll(self, job_id: str) -> TertiaryStructureJob: ...

    def fetch(self, job_id: str, output_dir: str | Path) -> str: ...


class NoopStructureLookupAdapter:
    def lookup(self, sequence: str) -> StructureLookupResult:
        return StructureLookupResult(
            status="not_configured",
            note="No structure lookup adapter is configured; using RNAfold.",
        )


class NoopStructureFetchAdapter:
    def fetch(self, match: StructureMatch, output_dir: str | Path) -> str:
        raise RuntimeError("No structure fetch adapter is configured.")


class NoopTertiaryStructureAdapter:
    def submit(self, sequence: str, secondary_structure: str) -> TertiaryStructureJob:
        return TertiaryStructureJob(
            status="not_configured",
            note="No tertiary-structure automation adapter is configured.",
        )

    def poll(self, job_id: str) -> TertiaryStructureJob:
        return TertiaryStructureJob(
            status="not_configured",
            job_id=job_id,
            note="No tertiary-structure automation adapter is configured.",
        )

    def fetch(self, job_id: str, output_dir: str | Path) -> str:
        raise RuntimeError("No tertiary-structure automation adapter is configured.")
