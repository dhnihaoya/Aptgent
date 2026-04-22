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


class _FakeAtom:
    def __init__(self, name: str, coord: tuple[float, float, float]) -> None:
        self.id = name
        self.name = name
        self.coord = coord

    def get_name(self) -> str:
        return self.name

    def get_coord(self) -> tuple[float, float, float]:
        return self.coord


class _FakeResidue:
    def __init__(self, resname: str, residue_number: int, atoms: list[_FakeAtom]) -> None:
        self.resname = resname
        self.id = (" ", residue_number, " ")
        self._atoms = {atom.name: atom for atom in atoms}

    def __getitem__(self, atom_name: str) -> _FakeAtom:
        return self._atoms[atom_name]

    def __iter__(self):
        return iter(self._atoms.values())


class _FakeChain:
    def __init__(self, chain_id: str, residues: list[_FakeResidue]) -> None:
        self.id = chain_id
        self._residues = residues

    def __iter__(self):
        return iter(self._residues)


class _FakeStructure:
    def __init__(self, chains: list[_FakeChain]) -> None:
        self._model = chains

    def get_models(self):
        yield self._model


class _FakeParser:
    def __init__(self, structure) -> None:
        self._structure = structure

    def get_structure(self, _structure_id, _path):
        return self._structure


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


def test_derive_secondary_structure_prefers_pdb_geometry(monkeypatch, tmp_path):
    adapter = PdbAnalysisAdapter()
    structure = _FakeStructure(
        [
            _FakeChain(
                "A",
                [
                    _FakeResidue(
                        "A",
                        1,
                        [
                            _FakeAtom("N1", (0.0, 0.0, 0.0)),
                            _FakeAtom("N6", (0.0, 0.0, 5.5)),
                            _FakeAtom("C1*", (0.0, 0.0, 0.0)),
                        ],
                    ),
                    _FakeResidue("C", 2, [_FakeAtom("C1*", (2.0, 0.0, 0.0))]),
                    _FakeResidue("G", 3, [_FakeAtom("C1*", (4.0, 0.0, 0.0))]),
                    _FakeResidue("C", 4, [_FakeAtom("C1*", (6.0, 0.0, 0.0))]),
                    _FakeResidue(
                        "U",
                        5,
                        [
                            _FakeAtom("N3", (0.0, 0.0, 3.0)),
                            _FakeAtom("O4", (0.0, 0.0, 8.4)),
                            _FakeAtom("C1*", (7.0, 0.0, 0.0)),
                        ],
                    ),
                ],
            )
        ]
    )
    monkeypatch.setattr(adapter, "_make_parser", lambda: _FakeParser(structure))
    artifact_path = tmp_path / "1EHZ.pdb"
    artifact_path.write_text("ATOM\n", encoding="utf-8")

    result = adapter.derive_secondary_structure(
        pdb_id="1EHZ",
        artifact_path=artifact_path,
        chain_id="A",
    )

    assert result.sequence == "ACGCU"
    assert result.dot_bracket == "(...)"
    assert result.features["source"] == "pdb"
    assert result.features["pair_count"] == 1


def test_derive_secondary_structure_errors_when_chain_missing(monkeypatch, tmp_path):
    adapter = PdbAnalysisAdapter()
    structure = _FakeStructure([_FakeChain("B", [])])
    monkeypatch.setattr(adapter, "_make_parser", lambda: _FakeParser(structure))
    artifact_path = tmp_path / "1EHZ.pdb"
    artifact_path.write_text("ATOM\n", encoding="utf-8")

    try:
        adapter.derive_secondary_structure(
            pdb_id="1EHZ",
            artifact_path=artifact_path,
            chain_id="A",
        )
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("Expected derive_secondary_structure() to fail for a missing chain.")

    assert "chain A" in message
