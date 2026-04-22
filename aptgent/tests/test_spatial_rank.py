from __future__ import annotations

import pytest

from aptgent.adapters.spatial_rank import SpatialRankAdapter, _RDKIT_AVAILABLE
from aptgent.domain.models import CandidateSequence, TargetMolecule


@pytest.fixture
def adapter(tmp_path):
    matrix_path = tmp_path / "test_matrix.csv"
    matrix_path.write_text(
        "base,Aromatic hydroxyl group,Methyl group,Benzene ring\n"
        "A,0.5,0.1,0.2\n"
        "T/U,0.1,0.4,0.3\n"
        "C,0.0,0.2,0.1\n"
        "G,0.8,0.0,0.6\n",
        encoding="utf-8",
    )
    return SpatialRankAdapter(str(matrix_path))


def test_load_matrix(adapter):
    assert adapter._groups == [
        "Aromatic hydroxyl group",
        "Methyl group",
        "Benzene ring",
    ]
    assert adapter._matrix["A"]["Methyl group"] == 0.1
    assert adapter._matrix["T/U"]["Benzene ring"] == 0.3


def test_map_base(adapter):
    assert adapter._map_base("a") == "A"
    assert adapter._map_base("T") == "T/U"
    assert adapter._map_base("U") == "T/U"
    assert adapter._map_base("x") is None


def test_score_sequence(adapter):
    present = {"Aromatic hydroxyl group": 1, "Methyl group": 2}
    # Sequence "AG"
    # A: 0.5*1 + 0.1*2 = 0.7
    # G: 0.8*1 + 0.0*2 = 0.8
    # total = 1.5, avg = 1.5 / 2 = 0.75
    score = adapter._score_sequence("AG", present)
    assert score == pytest.approx(0.75)


def test_score_sequence_empty_groups(adapter):
    assert adapter._score_sequence("AG", {}) == 0.0


def test_score_sequence_unknown_bases(adapter):
    present = {"Methyl group": 1}
    # "AxG" -> A and G only
    # A: 0.1, G: 0.0 -> total 0.1 / 3 = ~0.0333
    score = adapter._score_sequence("AxG", present)
    assert score == pytest.approx(0.1 / 3)


def test_rank_batch(adapter):
    candidates = [
        CandidateSequence(sequence="AA", candidate_id="c1"),
        CandidateSequence(sequence="GG", candidate_id="c2"),
    ]
    target = TargetMolecule(input_text="phenol", smiles="Oc1ccccc1")
    results = adapter.rank_batch(candidates, target)

    assert len(results) == 2
    # Both should have Aromatic hydroxyl group and Benzene ring detected
    assert "Aromatic hydroxyl group" in results[0].detected_groups
    assert "Benzene ring" in results[0].detected_groups

    # GG should score higher than AA because G has stronger interactions
    c1 = next(r for r in results if r.candidate_id == "c1")
    c2 = next(r for r in results if r.candidate_id == "c2")
    assert c2.spatial_score > c1.spatial_score
    assert c2.rank == 1
    assert c1.rank == 2


def test_rank_batch_no_smiles(adapter):
    candidates = [
        CandidateSequence(sequence="AA", candidate_id="c1"),
    ]
    target = TargetMolecule(input_text="unknown")
    results = adapter.rank_batch(candidates, target)
    assert results[0].spatial_score == 0.0
    assert results[0].rank == 1


@pytest.mark.skipif(_RDKIT_AVAILABLE, reason="Only when RDKit is missing")
def test_detect_groups_without_rdkit(adapter):
    assert adapter._detect_groups("Oc1ccccc1") == {}


@pytest.mark.skipif(not _RDKIT_AVAILABLE, reason="Requires RDKit")
def test_detect_groups_with_rdkit(adapter):
    counts = adapter._detect_groups("Oc1ccccc1")  # phenol
    assert counts.get("Aromatic hydroxyl group", 0) >= 1
    assert counts.get("Benzene ring", 0) >= 1


@pytest.mark.skipif(not _RDKIT_AVAILABLE, reason="Requires RDKit")
def test_detect_groups_caffeine(adapter):
    counts = adapter._detect_groups("CN1C=NC2=C1C(=O)N(C(=O)N2C)C")
    assert counts.get("Methyl group", 0) >= 1
    assert counts.get("Carbonyl group", 0) >= 1
