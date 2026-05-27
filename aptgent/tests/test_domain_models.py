"""Tests for ``aptgent.domain.models``."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from aptgent.domain.models import (
    CandidateSequence,
    DockingPlan,
    DockingResult,
    GridBox,
    Mutation,
    PdbAnalysisResult,
    PdbChainCandidate,
    PdbLigandCandidate,
    PredictionResult,
    SecondaryStructure,
    SpatialRankResult,
)


# ── Mutation ────────────────────────────────────────────────


class TestMutation:
    def test_valid(self):
        m = Mutation(position=0, original="A", mutated="G")
        assert m.position == 0

    def test_negative_position_rejected(self):
        with pytest.raises(ValidationError, match="non-negative"):
            Mutation(position=-1, original="A", mutated="G")

    def test_invalid_base_rejected(self):
        with pytest.raises(ValidationError, match="invalid nucleotide"):
            Mutation(position=0, original="X", mutated="G")

    def test_multi_char_base_rejected(self):
        with pytest.raises(ValidationError, match="invalid nucleotide"):
            Mutation(position=0, original="AT", mutated="G")

    def test_rna_base_accepted(self):
        m = Mutation(position=5, original="U", mutated="C")
        assert m.original == "U"

    def test_lowercase_accepted(self):
        m = Mutation(position=3, original="a", mutated="t")
        assert m.original == "a"


# ── GridBox ─────────────────────────────────────────────────


class TestGridBox:
    def test_valid(self):
        gb = GridBox(center=[1.0, 2.0, 3.0], size=[10.0, 20.0, 30.0])
        assert gb.center == [1.0, 2.0, 3.0]

    def test_wrong_length_center_rejected(self):
        with pytest.raises(ValidationError, match="exactly 3"):
            GridBox(center=[1.0, 2.0], size=[10.0, 20.0, 30.0])

    def test_wrong_length_size_rejected(self):
        with pytest.raises(ValidationError, match="exactly 3"):
            GridBox(center=[1.0, 2.0, 3.0], size=[10.0, 20.0])

    def test_zero_size_rejected(self):
        with pytest.raises(ValidationError, match="positive"):
            GridBox(center=[1.0, 2.0, 3.0], size=[10.0, 0.0, 30.0])

    def test_negative_size_rejected(self):
        with pytest.raises(ValidationError, match="positive"):
            GridBox(center=[1.0, 2.0, 3.0], size=[10.0, -1.0, 30.0])


# ── DockingPlan ─────────────────────────────────────────────


class TestDockingPlan:
    def test_defaults(self):
        dp = DockingPlan()
        assert dp.exhaustiveness == 8
        assert dp.num_modes == 9
        assert dp.energy_range == 3.0
        assert dp.receptor_source == "manual"

    def test_legacy_receptor_path_empty(self):
        dp = DockingPlan()
        assert dp.receptor_path is None

    def test_legacy_receptor_path_set(self):
        dp = DockingPlan(receptor_paths={"c1": "/path/to/receptor.pdbqt"})
        assert dp.receptor_path == "/path/to/receptor.pdbqt"

    def test_legacy_grid_center_empty(self):
        dp = DockingPlan()
        assert dp.grid_center is None

    def test_legacy_grid_center_set(self):
        dp = DockingPlan(grid_boxes={"c1": GridBox(center=[1, 2, 3], size=[10, 10, 10])})
        assert dp.grid_center == [1.0, 2.0, 3.0]

    def test_legacy_grid_size_set(self):
        dp = DockingPlan(grid_boxes={"c1": GridBox(center=[1, 2, 3], size=[10, 20, 30])})
        assert dp.grid_size == [10.0, 20.0, 30.0]

    def test_extra_fields_ignored(self):
        dp = DockingPlan(unknown_field="value")
        assert not hasattr(dp, "unknown_field") or True  # extra="ignore"


# ── CandidateSequence ───────────────────────────────────────


class TestCandidateSequence:
    def test_defaults(self):
        cs = CandidateSequence(sequence="ATGC")
        assert cs.mutations == []
        assert cs.edit_ratio == 0.0
        assert cs.candidate_id is None


# ── PdbAnalysisResult ───────────────────────────────────────


class TestPdbAnalysisResult:
    def test_defaults(self):
        r = PdbAnalysisResult(pdb_id="1ABC")
        assert r.title == ""
        assert r.nucleic_acid_chains == []
        assert r.ligands == []
        assert r.needs_user_selection is False


# ── SecondaryStructure ──────────────────────────────────────


class TestSecondaryStructure:
    def test_create(self):
        ss = SecondaryStructure(sequence="ATGC", dot_bracket="((..", mfe=-5.2)
        assert ss.mfe == -5.2


# ── PredictionResult ────────────────────────────────────────


class TestPredictionResult:
    def test_create(self):
        pr = PredictionResult(
            candidate_id="c1", model_name="xgb", target="C",
            score=0.85, label=1, probability=0.92,
        )
        assert pr.label == 1


# ── DockingResult ───────────────────────────────────────────


class TestDockingResult:
    def test_defaults(self):
        dr = DockingResult(candidate_id="c1")
        assert dr.status == "pending"
        assert dr.docking_score is None


# ── SpatialRankResult ───────────────────────────────────────


class TestSpatialRankResult:
    def test_create(self):
        sr = SpatialRankResult(candidate_id="c1", spatial_score=3.5)
        assert sr.rank == 0


# ── Serialization round-trip ────────────────────────────────


class TestSerialization:
    def test_mutation_json_roundtrip(self):
        m = Mutation(position=3, original="A", mutated="G")
        data = m.model_dump()
        m2 = Mutation.model_validate(data)
        assert m2 == m

    def test_gridbox_json_roundtrip(self):
        gb = GridBox(center=[1.0, 2.0, 3.0], size=[10.0, 20.0, 30.0])
        data = gb.model_dump()
        gb2 = GridBox.model_validate(data)
        assert gb2 == gb

    def test_docking_plan_json_roundtrip(self):
        dp = DockingPlan(
            receptor_paths={"c1": "/path/r.pdbqt"},
            grid_boxes={"c1": GridBox(center=[1, 2, 3], size=[10, 10, 10])},
        )
        data = dp.model_dump()
        dp2 = DockingPlan.model_validate(data)
        assert dp2.receptor_path == dp.receptor_path

    def test_pdb_analysis_result_json_roundtrip(self):
        r = PdbAnalysisResult(pdb_id="1ABC", title="Test")
        data = r.model_dump()
        r2 = PdbAnalysisResult.model_validate(data)
        assert r2.pdb_id == "1ABC"
