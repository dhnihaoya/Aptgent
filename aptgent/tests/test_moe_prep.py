from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aptgent.adapters.moe_prep import MoePreparationAdapter


def test_is_available_true():
    with patch("aptgent.adapters.moe_prep.shutil.which", return_value="/usr/bin/moebatch"):
        assert MoePreparationAdapter.is_available("moebatch") is True


def test_is_available_false():
    with patch("aptgent.adapters.moe_prep.shutil.which", return_value=None):
        assert MoePreparationAdapter.is_available("moebatch") is False


def test_svl_script_path():
    adapter = MoePreparationAdapter()
    path = adapter.svl_script_path
    assert path.name == "moe_rna2dna_min.svl"
    assert "resources" in str(path)


def test_convert_rna_to_dna_minimize_success(tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()

    # Create fake input PDBs
    for cid in ["cand_0", "cand_1"]:
        (input_dir / f"{cid}.pdb").write_text("fake pdb\n")

    adapter = MoePreparationAdapter(moebatch_command="moebatch")

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stderr = ""

    def fake_run(cmd, **kwargs):
        # Simulate moebatch creating output files
        out_dir = Path(kwargs["env"]["APT_OUT"])
        for cid in ["cand_0", "cand_1"]:
            (out_dir / f"{cid}.pdb").write_text("minimized pdb\n")
        return mock_proc

    with patch("aptgent.adapters.moe_prep.shutil.which", return_value="/usr/bin/moebatch"), \
         patch("aptgent.adapters.moe_prep.subprocess.run", side_effect=fake_run):
        results = adapter.convert_rna_to_dna_minimize(
            input_dir, output_dir, ["cand_0", "cand_1"],
        )

    assert "cand_0" in results
    assert "cand_1" in results
    assert results["cand_0"].exists()


def test_convert_rna_to_dna_minimize_partial_failure(tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()

    for cid in ["cand_0", "cand_1"]:
        (input_dir / f"{cid}.pdb").write_text("fake pdb\n")

    adapter = MoePreparationAdapter(moebatch_command="moebatch")

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stderr = ""

    def fake_run(cmd, **kwargs):
        out_dir = Path(kwargs["env"]["APT_OUT"])
        # Only create one output
        (out_dir / "cand_0.pdb").write_text("minimized pdb\n")
        return mock_proc

    with patch("aptgent.adapters.moe_prep.shutil.which", return_value="/usr/bin/moebatch"), \
         patch("aptgent.adapters.moe_prep.subprocess.run", side_effect=fake_run):
        results = adapter.convert_rna_to_dna_minimize(
            input_dir, output_dir, ["cand_0", "cand_1"],
        )

    assert "cand_0" in results
    assert "cand_1" not in results


def test_convert_rna_to_dna_minimize_all_fail(tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()

    (input_dir / "cand_0.pdb").write_text("fake pdb\n")

    adapter = MoePreparationAdapter(moebatch_command="moebatch")

    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_proc.stderr = "license error"

    with patch("aptgent.adapters.moe_prep.shutil.which", return_value="/usr/bin/moebatch"), \
         patch("aptgent.adapters.moe_prep.subprocess.run", return_value=mock_proc):
        with pytest.raises(RuntimeError, match="moebatch failed"):
            adapter.convert_rna_to_dna_minimize(
                input_dir, output_dir, ["cand_0"],
            )


def test_convert_rna_to_dna_minimize_not_available(tmp_path):
    adapter = MoePreparationAdapter(moebatch_command="moebatch")

    with patch("aptgent.adapters.moe_prep.shutil.which", return_value=None):
        with pytest.raises(FileNotFoundError, match="not found"):
            adapter.convert_rna_to_dna_minimize(
                tmp_path, tmp_path / "out", ["cand_0"],
            )


def test_prepare_pdbqt_delegates(tmp_path):
    adapter = MoePreparationAdapter()

    with patch.object(adapter._receptor_prep, "prepare_pdbqt", return_value=Path("/out.pdbqt")) as mock:
        result = adapter.prepare_pdbqt("/in.pdb", "/out.pdbqt")

    mock.assert_called_once_with("/in.pdb", "/out.pdbqt", treat_as_dna=False)
    assert result == Path("/out.pdbqt")


def test_compute_box_delegates(tmp_path):
    adapter = MoePreparationAdapter()

    with patch.object(adapter._receptor_prep, "compute_box", return_value="box") as mock:
        result = adapter.compute_box("/in.pdbqt", padding=5.0)

    mock.assert_called_once_with("/in.pdbqt", padding=5.0)
    assert result == "box"


def test_progress_callback(tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()

    (input_dir / "cand_0.pdb").write_text("fake pdb\n")

    adapter = MoePreparationAdapter(moebatch_command="moebatch")
    progress_messages: list[str] = []

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stderr = ""

    def fake_run(cmd, **kwargs):
        out_dir = Path(kwargs["env"]["APT_OUT"])
        (out_dir / "cand_0.pdb").write_text("minimized\n")
        return mock_proc

    with patch("aptgent.adapters.moe_prep.shutil.which", return_value="/usr/bin/moebatch"), \
         patch("aptgent.adapters.moe_prep.subprocess.run", side_effect=fake_run):
        adapter.convert_rna_to_dna_minimize(
            input_dir, output_dir, ["cand_0"],
            on_progress=progress_messages.append,
        )

    assert len(progress_messages) >= 1
    assert any("1" in msg for msg in progress_messages)


def test_on_file_done_called_per_candidate(tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()

    for cid in ["cand_0", "cand_1", "cand_2"]:
        (input_dir / f"{cid}.pdb").write_text("fake pdb\n")

    adapter = MoePreparationAdapter(moebatch_command="moebatch")
    done_events: list[tuple[int, int]] = []

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stderr = ""

    def fake_run(cmd, **kwargs):
        out_dir = Path(kwargs["env"]["APT_OUT"])
        # Each per-file invocation isolates one candidate in APT_IN.
        for src in Path(kwargs["env"]["APT_IN"]).glob("*.pdb"):
            (out_dir / src.name).write_text("minimized\n")
        return mock_proc

    with patch("aptgent.adapters.moe_prep.shutil.which", return_value="/usr/bin/moebatch"), \
         patch("aptgent.adapters.moe_prep.subprocess.run", side_effect=fake_run):
        adapter.convert_rna_to_dna_minimize(
            input_dir, output_dir, ["cand_0", "cand_1", "cand_2"],
            on_file_done=lambda done, total: done_events.append((done, total)),
        )

    assert done_events == [(1, 3), (2, 3), (3, 3)]


def test_run_one_symlink_uses_absolute_target(tmp_path):
    """moebatch may run with a different cwd; input symlinks must be absolute."""
    input_dir = tmp_path / "structures"
    output_dir = tmp_path / "out"
    input_dir.mkdir()
    (input_dir / "cand_0.pdb").write_text("fake pdb\n")

    adapter = MoePreparationAdapter(moebatch_command="moebatch")
    link_targets: list[Path] = []
    real_symlink_to = Path.symlink_to

    def capture_symlink(self, target, *args, **kwargs):
        link_targets.append(Path(target))
        return real_symlink_to(self, target, *args, **kwargs)

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stderr = ""
    mock_proc.stdout = ""

    def fake_run(cmd, **kwargs):
        apt_in = Path(kwargs["env"]["APT_IN"])
        out_dir = Path(kwargs["env"]["APT_OUT"])
        out_dir.mkdir(parents=True, exist_ok=True)
        for src in apt_in.glob("*.pdb"):
            if not src.resolve().exists():
                return mock_proc
            (out_dir / src.name).write_text("minimized\n")
        return mock_proc

    with patch("aptgent.adapters.moe_prep.shutil.which", return_value="/usr/bin/moebatch"), \
         patch("aptgent.adapters.moe_prep.subprocess.run", side_effect=fake_run), \
         patch.object(Path, "symlink_to", capture_symlink):
        result = adapter.convert_rna_to_dna_minimize(
            input_dir, output_dir, ["cand_0"],
        )

    assert link_targets
    assert link_targets[0].is_absolute()
    assert result["cand_0"].exists()
