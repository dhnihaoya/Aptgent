from __future__ import annotations

import pytest

from aptgent.adapters.spatial_rank import SpatialRankAdapter, _RDKIT_AVAILABLE
from aptgent.domain.models import (
    CandidateSequence,
    DockingResult,
    TargetMolecule,
)


def _atom_line(serial, name, resname, chain, resseq, x, y, z):
    """Build a fixed-column PDB/PDBQT ATOM line."""
    return (
        f"ATOM  {serial:>5} {name:<4}{'':1}{resname:>3} {chain}{resseq:>4}{'':1}   "
        f"{x:8.3f}{y:8.3f}{z:8.3f}  0.00  0.00    0.000 X "
    )


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


# ── pose-based ranking: parsers ─────────────────────────────


def test_preferred_bases(adapter):
    preferred = adapter._preferred_bases()
    # Aromatic hydroxyl group: A=0.5 T/U=0.1 C=0.0 G=0.8 -> G
    assert preferred["Aromatic hydroxyl group"] == "G"
    # Methyl group: A=0.1 T/U=0.4 C=0.2 G=0.0 -> T/U
    assert preferred["Methyl group"] == "T/U"
    # Benzene ring: A=0.2 T/U=0.3 C=0.1 G=0.6 -> G
    assert preferred["Benzene ring"] == "G"


def test_parse_receptor_bases(adapter, tmp_path):
    receptor = tmp_path / "receptor.pdbqt"
    receptor.write_text(
        "\n".join(
            [
                _atom_line(1, "N1", "DA", "A", 1, 1.0, 0.0, 0.0),
                _atom_line(2, "N3", "DT", "A", 2, 2.0, 0.0, 0.0),
                _atom_line(3, "N1", "DC", "A", 3, 3.0, 0.0, 0.0),
                _atom_line(4, "N9", "DG", "A", 4, 4.0, 0.0, 0.0),
                "HETATM    5  O   HOH B   1       9.000   9.000   9.000",
                "TER",
            ]
        ),
        encoding="utf-8",
    )
    bases = adapter._parse_receptor_bases(str(receptor))
    assert [b[0] for b in bases] == ["A", "T/U", "C", "G"]
    # First base (DA) keeps its single atom coordinate.
    assert bases[0][2][0][1] == pytest.approx(1.0)


def test_parse_first_pose_atoms_only_first_model(adapter, tmp_path):
    pose = tmp_path / "out.pdbqt"
    pose.write_text(
        "\n".join(
            [
                "MODEL 1",
                "REMARK VINA RESULT:   -6.5  0.000  0.000",
                _atom_line(1, "C", "UNL", "A", 1, 0.0, 0.0, 0.0),
                _atom_line(2, "O", "UNL", "A", 1, 1.0, 0.0, 0.0),
                "ENDMDL",
                "MODEL 2",
                _atom_line(1, "C", "UNL", "A", 1, 5.0, 5.0, 5.0),
                "ENDMDL",
            ]
        ),
        encoding="utf-8",
    )
    atoms = adapter._parse_first_pose_atoms(str(pose))
    assert len(atoms) == 2
    assert atoms[0][1] == pytest.approx(0.0)
    assert atoms[1][1] == pytest.approx(1.0)


def test_map_ligand_atoms_to_groups(adapter):
    pose_atoms = [
        ("C", 0.0, 0.0, 0.0),
        ("O", 1.0, 0.0, 0.0),
        ("N", 2.0, 0.0, 0.0),
    ]
    group_matches = {"Methyl group": [(0,), (2,)], "Out of range": [(99,)]}
    mapped = adapter._map_ligand_atoms_to_groups(group_matches, pose_atoms)
    assert "Out of range" not in mapped
    assert len(mapped["Methyl group"]) == 2
    assert mapped["Methyl group"][0][0][1] == pytest.approx(0.0)
    assert mapped["Methyl group"][1][0][1] == pytest.approx(2.0)


def test_heavy_pose_atoms_drops_hydrogens(adapter):
    pose = [
        ("C", 0.0, 0.0, 0.0),
        ("HD", 1.0, 0.0, 0.0),
        ("O", 2.0, 0.0, 0.0),
        ("H", 3.0, 0.0, 0.0),
    ]
    heavy = adapter._heavy_pose_atoms(pose)
    assert [a[0] for a in heavy] == ["C", "O"]


def test_map_drops_hydrogens_before_indexing(adapter):
    # Hydrogens between heavy atoms must not shift the heavy-atom index map.
    pose = [
        ("C", 0.0, 0.0, 0.0),
        ("HD", 9.0, 9.0, 9.0),
        ("O", 2.0, 0.0, 0.0),
    ]
    group_matches = {"g": [(1,)]}  # RDKit heavy index 1 -> O (not the H)
    mapped = adapter._map_ligand_atoms_to_groups(group_matches, pose)
    assert mapped["g"][0][0][0] == "O"
    assert mapped["g"][0][0][1] == pytest.approx(2.0)


def test_count_rule_matches(adapter):
    # One G base at origin.
    receptor_bases = [("G", "A:DG:1", [("N9", 0.0, 0.0, 0.0)])]
    preferred = {"Benzene ring": "G"}
    # Occurrence 1 within cutoff (2 A), occurrence 2 far (10 A).
    ligand_group_atoms = {
        "Benzene ring": [
            [("C", 2.0, 0.0, 0.0)],
            [("C", 10.0, 0.0, 0.0)],
        ]
    }
    count, details = adapter._count_rule_matches(
        receptor_bases, ligand_group_atoms, preferred, cutoff=4.0
    )
    assert count == 1
    assert details[0]["preferred_base"] == "G"
    assert details[0]["distance"] == pytest.approx(2.0)


def test_count_rule_matches_wrong_base_type(adapter):
    # Only an A base present, but preferred base is G -> no match.
    receptor_bases = [("A", "A:DA:1", [("N1", 0.0, 0.0, 0.0)])]
    preferred = {"Benzene ring": "G"}
    ligand_group_atoms = {"Benzene ring": [[("C", 1.0, 0.0, 0.0)]]}
    count, _ = adapter._count_rule_matches(
        receptor_bases, ligand_group_atoms, preferred, cutoff=4.0
    )
    assert count == 0


# ── pose-based ranking: ranking helpers ─────────────────────


def test_competition_and_dense_ranks(adapter):
    counts = [3.0, 3.0, 2.0, 1.0, 0.0, 0.0, 0.0]
    comp = adapter._competition_ranks(counts, reverse=True)
    assert comp == [1, 1, 3, 4, 5, 5, 5]

    scores = [-6.7, -7.1, -6.4, -6.5, -6.6, -6.5, -6.5]
    dense = adapter._dense_ranks(scores, reverse=False)
    # ascending unique: -7.1,-6.7,-6.6,-6.5,-6.4 -> 1..5
    assert dense == [2, 1, 5, 4, 3, 4, 4]


def test_rank_pose_reproduces_paper_table(adapter, tmp_path):
    """Exact reproduction of paper Table 2 ranking."""
    receptor = tmp_path / "receptor.pdbqt"
    receptor.write_text(
        _atom_line(1, "N9", "DG", "A", 1, 0.0, 0.0, 0.0), encoding="utf-8"
    )
    pose = tmp_path / "out.pdbqt"
    pose.write_text(
        _atom_line(1, "C", "UNL", "A", 1, 0.0, 0.0, 0.0), encoding="utf-8"
    )

    # candidate order = paper order; ties resolve via stable input order.
    table = [
        ("Mut88", 3, -6.7),
        ("Mut16", 1, -7.1),
        ("Mut48", 3, -6.4),
        ("Mut89", 2, -6.5),
        ("Mut67", 0, -6.6),
        ("Mut9", 0, -6.5),
        ("Mut78", 0, -6.5),
    ]
    candidates = [CandidateSequence(sequence="AAAA", candidate_id=cid) for cid, _, _ in table]
    docking_results = [
        DockingResult(
            candidate_id=cid,
            docking_score=score,
            status="completed",
            raw_outputs={
                "output_pdbqt": str(pose),
                "receptor_pdbqt": str(receptor),
            },
        )
        for cid, _, score in table
    ]

    counts = iter([c for _, c, _ in table])
    adapter._detect_group_matches = lambda smiles: {"Benzene ring": [(0,)]}
    adapter._count_rule_matches = lambda *a, **k: (next(counts), [])

    target = TargetMolecule(input_text="x", smiles="c1ccccc1")
    results = adapter._rank_pose(candidates, target, docking_results)
    by_id = {r.candidate_id: r for r in results}

    expected = {
        "Mut88": (1, 2, 3, 1),
        "Mut16": (4, 1, 5, 2),
        "Mut48": (1, 5, 6, 3),
        "Mut89": (3, 4, 7, 4),
        "Mut67": (5, 3, 8, 5),
        "Mut9": (5, 4, 9, 6),
        "Mut78": (5, 4, 9, 7),
    }
    for cid, (irank, drank, rsum, final) in expected.items():
        raw = by_id[cid].raw_outputs
        assert raw["mode"] == "pose_rule_match"
        assert raw["interaction_rank"] == irank, cid
        assert raw["docking_rank"] == drank, cid
        assert raw["rank_sum"] == rsum, cid
        assert by_id[cid].rank == final, cid


def test_rank_pose_marks_no_pose_for_missing_files(adapter, tmp_path, monkeypatch):
    receptor = tmp_path / "receptor.pdbqt"
    receptor.write_text(
        _atom_line(1, "N9", "DG", "A", 1, 0.0, 0.0, 0.0), encoding="utf-8"
    )
    pose = tmp_path / "out.pdbqt"
    pose.write_text(
        _atom_line(1, "C", "UNL", "A", 1, 0.0, 0.0, 0.0), encoding="utf-8"
    )
    candidates = [
        CandidateSequence(sequence="AAAA", candidate_id="c1"),
        CandidateSequence(sequence="AAAA", candidate_id="c2"),
    ]
    docking_results = [
        DockingResult(
            candidate_id="c1",
            docking_score=-6.5,
            status="completed",
            raw_outputs={
                "output_pdbqt": str(pose),
                "receptor_pdbqt": str(receptor),
            },
        ),
        DockingResult(
            candidate_id="c2",
            docking_score=None,
            status="missing_receptor",
            raw_outputs={},
        ),
    ]
    monkeypatch.setattr(
        adapter, "_detect_group_matches", lambda smiles: {"Benzene ring": [(0,)]}
    )
    target = TargetMolecule(input_text="x", smiles="c1ccccc1")
    results = adapter._rank_pose(candidates, target, docking_results)
    by_id = {r.candidate_id: r for r in results}

    assert by_id["c1"].raw_outputs["mode"] == "pose_rule_match"
    assert by_id["c2"].raw_outputs["mode"] == "no_pose"
    assert by_id["c2"].raw_outputs["interaction_count"] == 0
    # c2 has no pose, so the atom-map reliability flag must be absent.
    assert "atom_map_reliable" not in by_id["c2"].raw_outputs


@pytest.mark.skipif(not _RDKIT_AVAILABLE, reason="Requires RDKit")
def test_rank_pose_flags_atom_map_unreliable_on_count_mismatch(
    adapter, tmp_path, monkeypatch
):
    receptor = tmp_path / "receptor.pdbqt"
    receptor.write_text(
        _atom_line(1, "N9", "DG", "A", 1, 0.0, 0.0, 0.0), encoding="utf-8"
    )
    # Pose has a single heavy atom but benzene has 6 -> mapping unreliable.
    pose = tmp_path / "out.pdbqt"
    pose.write_text(
        _atom_line(1, "C", "UNL", "A", 1, 0.0, 0.0, 0.0), encoding="utf-8"
    )
    candidates = [CandidateSequence(sequence="AAAA", candidate_id="c1")]
    docking_results = [
        DockingResult(
            candidate_id="c1",
            docking_score=-6.5,
            status="completed",
            raw_outputs={
                "output_pdbqt": str(pose),
                "receptor_pdbqt": str(receptor),
            },
        )
    ]
    monkeypatch.setattr(
        adapter, "_detect_group_matches", lambda smiles: {"Benzene ring": [(0,)]}
    )
    target = TargetMolecule(input_text="benzene", smiles="c1ccccc1")
    results = adapter._rank_pose(candidates, target, docking_results)
    assert results[0].raw_outputs["atom_map_reliable"] is False


# ── fallback / dispatch ─────────────────────────────────────


def test_rank_batch_fallback_marks_mode(adapter):
    candidates = [CandidateSequence(sequence="AG", candidate_id="c1")]
    target = TargetMolecule(input_text="phenol", smiles="Oc1ccccc1")
    results = adapter.rank_batch(candidates, target, docking_results=None)
    assert results[0].raw_outputs["mode"] == "sequence_fallback"


def test_rank_batch_dispatches_to_pose_mode(adapter, tmp_path, monkeypatch):
    receptor = tmp_path / "receptor.pdbqt"
    receptor.write_text(
        _atom_line(1, "N9", "DG", "A", 1, 0.0, 0.0, 0.0), encoding="utf-8"
    )
    pose = tmp_path / "out.pdbqt"
    pose.write_text(
        _atom_line(1, "C", "UNL", "A", 1, 0.0, 0.0, 0.0), encoding="utf-8"
    )
    candidates = [CandidateSequence(sequence="AAAA", candidate_id="c1")]
    docking_results = [
        DockingResult(
            candidate_id="c1",
            docking_score=-6.5,
            status="completed",
            raw_outputs={
                "output_pdbqt": str(pose),
                "receptor_pdbqt": str(receptor),
            },
        )
    ]
    monkeypatch.setattr(
        adapter, "_detect_group_matches", lambda smiles: {"Benzene ring": [(0,)]}
    )
    target = TargetMolecule(input_text="x", smiles="c1ccccc1")
    results = adapter.rank_batch(candidates, target, docking_results)
    assert results[0].raw_outputs["mode"] == "pose_rule_match"
    # Benzene ring prefers G; ligand atom 0 sits on the G base -> 1 match.
    assert results[0].raw_outputs["interaction_count"] == 1
    assert results[0].rank == 1
