from __future__ import annotations

import pytest

from aptgent.adapters.receptor_prep import (
    BoundingBox,
    ReceptorPreparationAdapter,
    dna_to_rna,
    export_top_k_sequences,
    revert_ribose_to_deoxyribose,
    rna_to_dna,
    scan_structure_directory,
)


def test_dna_to_rna_and_back():
    assert dna_to_rna("ACGT") == "ACGU"
    assert dna_to_rna("acgt") == "acgu"
    assert rna_to_dna("ACGU") == "ACGT"
    # Round-trip
    assert rna_to_dna(dna_to_rna("ACGTACGT")) == "ACGTACGT"


def test_revert_ribose_to_deoxyribose_strips_o2_and_renames_residues():
    # PDB columns (1-indexed): 1-6 ATOM, 7-11 serial, 13-16 atom name,
    # 17 altLoc, 18-20 resName (right-justified), 22 chainID, 23-26 resSeq.
    pdb = (
        "HEADER    RNA model\n"
        "ATOM      1  P     A A   1      10.000  20.000  30.000  1.00  0.00           P\n"
        "ATOM      2  O2'  A A   1      10.500  20.500  30.500  1.00  0.00           O\n"
        "ATOM      3 HO2'  A A   1      10.700  20.700  30.700  1.00  0.00           H\n"
        "ATOM      4  C1'  A A   1      11.000  21.000  31.000  1.00  0.00           C\n"
        "ATOM      5  P     U A   2      12.000  22.000  32.000  1.00  0.00           P\n"
        "ATOM      6  O2'  U A   2      12.500  22.500  32.500  1.00  0.00           O\n"
        "TER\n"
        "END\n"
    )
    result = revert_ribose_to_deoxyribose(pdb)
    # Every O2'-family atom record was dropped.
    assert " O2' " not in result
    assert "HO2'" not in result
    assert " DA " in result
    assert " DT " in result
    # Other atom records remain intact.
    assert " C1' " in result


def test_compute_box_returns_bbox_with_padding(tmp_path):
    pdb = tmp_path / "tiny.pdb"
    pdb.write_text(
        "ATOM      1  P     A A   1       0.000   0.000   0.000  1.00  0.00           P\n"
        "ATOM      2  P     A A   2      10.000  10.000  10.000  1.00  0.00           P\n",
        encoding="utf-8",
    )
    adapter = ReceptorPreparationAdapter(default_padding=2.0)
    box = adapter.compute_box(pdb)
    assert isinstance(box, BoundingBox)
    assert box.center == (5.0, 5.0, 5.0)
    assert box.size == (14.0, 14.0, 14.0)


def test_compute_box_raises_when_no_atoms(tmp_path):
    pdb = tmp_path / "empty.pdb"
    pdb.write_text("HEADER\nEND\n", encoding="utf-8")
    adapter = ReceptorPreparationAdapter()
    with pytest.raises(ValueError):
        adapter.compute_box(pdb)


def test_prepare_pdbqt_raises_when_obabel_missing(tmp_path):
    pdb = tmp_path / "in.pdb"
    pdb.write_text(
        "ATOM      1  P     A A   1       0.000   0.000   0.000  1.00  0.00           P\n",
        encoding="utf-8",
    )
    adapter = ReceptorPreparationAdapter(obabel_command="definitely-not-a-real-binary-xyz")
    with pytest.raises(FileNotFoundError):
        adapter.prepare_pdbqt(pdb, tmp_path / "out.pdbqt", treat_as_dna=False)


def test_export_top_k_sequences_writes_fasta_and_tsv(tmp_path):
    out_dir = tmp_path / "seqs"
    out = export_top_k_sequences(
        [("cand_0", "ACGT"), ("cand_1", "TTTT")],
        out_dir,
    )
    assert out == out_dir.resolve()
    tsv = (out_dir / "sequences.tsv").read_text()
    assert "cand_0\tACGT" in tsv
    assert "cand_1\tTTTT" in tsv
    assert (out_dir / "cand_0.fasta").read_text().startswith(">cand_0")


def test_scan_structure_directory_finds_files(tmp_path):
    base = tmp_path / "structs"
    base.mkdir()
    (base / "cand_0.pdb").write_text("HEADER\n", encoding="utf-8")
    (base / "cand_1.pdbqt").write_text("HEADER\n", encoding="utf-8")
    # Untracked file should be ignored
    (base / "ignore.txt").write_text("noise", encoding="utf-8")
    result = scan_structure_directory(base, ["cand_0", "cand_1", "cand_2"])
    assert "cand_0" in result and "pdb" in result["cand_0"]
    assert "cand_1" in result and "pdbqt" in result["cand_1"]
    assert "cand_2" not in result


def test_scan_structure_directory_handles_missing_dir(tmp_path):
    assert scan_structure_directory(tmp_path / "nope", ["cand_0"]) == {}


def test_energy_minimize_raises_when_binary_missing(tmp_path):
    pdb = tmp_path / "in.pdb"
    pdb.write_text(
        "ATOM      1  P     A A   1       0.000   0.000   0.000  1.00  0.00           P\n",
        encoding="utf-8",
    )
    adapter = ReceptorPreparationAdapter(
        minimize_command="definitely-not-a-real-binary-xyz",
    )
    with pytest.raises(FileNotFoundError):
        adapter.energy_minimize(pdb, tmp_path / "out.pdb")


def test_energy_minimize_raises_when_input_missing(tmp_path):
    adapter = ReceptorPreparationAdapter()
    with pytest.raises(FileNotFoundError):
        adapter.energy_minimize(tmp_path / "nope.pdb", tmp_path / "out.pdb")


def test_energy_minimize_returns_output_on_success(tmp_path, monkeypatch):
    pdb = tmp_path / "in.pdb"
    pdb.write_text(
        "ATOM      1  P     A A   1       0.000   0.000   0.000  1.00  0.00           P\n",
        encoding="utf-8",
    )
    out = tmp_path / "out.pdb"
    adapter = ReceptorPreparationAdapter(minimize_steps=100)

    import subprocess
    from unittest.mock import patch

    def fake_run(cmd, **kwargs):
        out.write_text(
            "ATOM      1  P     A A   1       0.001   0.001   0.001  1.00  0.00           P\n",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    with patch("aptgent.adapters.receptor_prep.subprocess.run", side_effect=fake_run):
        result = adapter.energy_minimize(pdb, out)

    assert result == out
    assert out.exists()
