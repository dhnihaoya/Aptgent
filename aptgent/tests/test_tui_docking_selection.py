from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest
from textual.css.query import NoMatches
from textual.widgets import Button, Input

from aptgent.adapters.receptor_prep import BoundingBox
from aptgent.adapters.structure_services import TertiaryStructureJob
from aptgent.domain.enums import Step
from aptgent.domain.models import (
    CandidateSequence,
    DockingPlan,
    GridBox,
)
from aptgent.tui.steps import docking_selection as docking_selection_module
from aptgent.tui.widgets.structured_input import (
    DockingManualUploadPanel,
    DockingParamPanel,
    DockingSourcePanel,
    DockingStrategyPanel,
)

from tui_helpers import anyio_backend, make_app

_log = logging.getLogger(__name__)


class FakeReceptorPrepAdapter:
    """Stand-in that fakes Open Babel / bbox calls deterministically."""

    def __init__(self) -> None:
        self.prepare_calls: list[tuple[str, str]] = []
        self.box_calls: list[str] = []

    def dna_to_rna(self, sequence: str) -> str:
        return sequence.replace("T", "U")

    def rna_to_dna(self, sequence: str) -> str:
        return sequence.replace("U", "T")

    def revert_ribose_to_deoxyribose(self, text: str) -> str:
        return text.replace("U A ", "DT A ")

    def energy_minimize(
        self,
        pdb_path: str | Path,
        output_path: str | Path,
    ) -> Path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(Path(pdb_path).read_text(encoding="utf-8"), encoding="utf-8")
        return out

    def prepare_pdbqt(
        self,
        pdb_path: str | Path,
        output_path: str | Path,
        *,
        treat_as_dna: bool = True,
    ) -> Path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("FAKE PDBQT", encoding="utf-8")
        self.prepare_calls.append((str(pdb_path), str(out)))
        return out

    def compute_box(self, path: str | Path, *, padding: float = 0.0) -> BoundingBox:
        self.box_calls.append(str(path))
        return BoundingBox(
            center=(1.0, 2.0, 3.0),
            size=(10.0 + 2 * padding, 11.0 + 2 * padding, 12.0 + 2 * padding),
            padding=padding,
            atom_count=10,
        )


class FakeRNAComposerAdapter:
    """Pretends to be RNAComposer; writes a stub PDB per candidate."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def predict_to_path(
        self,
        sequence: str,
        secondary_structure: str = "",
        output_dir: str | Path = ".",
        *,
        candidate_id: str | None = None,
        on_poll: Any = None,
    ) -> str:
        self.calls.append(sequence)
        out = Path(output_dir) / f"{candidate_id or 'cand'}.pdb"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            "ATOM      1  P     U A   1       0.000   0.000   0.000  1.00  0.00           P\n",
            encoding="utf-8",
        )
        return str(out)

    def submit(self, sequence: str, secondary_structure: str) -> TertiaryStructureJob:
        return TertiaryStructureJob(provider="rnacomposer", status="completed", job_id="fake")

    def poll(self, job_id: str) -> TertiaryStructureJob:
        return TertiaryStructureJob(provider="rnacomposer", status="completed", job_id=job_id)

    def fetch(self, job_id: str, output_dir: str | Path) -> str:
        return str(output_dir)


def _attach_fake_adapters(app: Any) -> tuple[FakeReceptorPrepAdapter, FakeRNAComposerAdapter]:
    prep = FakeReceptorPrepAdapter()
    rna = FakeRNAComposerAdapter()
    app.receptor_prep_adapter = prep
    app.tertiary_structure_adapter = rna
    return prep, rna


@pytest.mark.anyio
async def test_topk_panel_renders_with_paper_default(tmp_path):
    app = make_app(tmp_path)
    state = app.engine.create_run("dock_topk_case")
    state.current_step = Step.DOCKING_SELECTION
    state.candidates = [
        CandidateSequence(sequence=f"ACGT{i:02d}", candidate_id=f"cand-{i}")
        for i in range(1, 21)
    ]
    app.persistence.save(state)

    async with app.run_test() as pilot:
        await pilot.pause()
        _attach_fake_adapters(app)
        app.set_run_id("dock_topk_case")
        app.push_screen("chat")
        await pilot.pause()
        await pilot.pause()

        panel = app.screen.query_one(DockingStrategyPanel)
        assert panel.query_one("#dock-plan-top-k", Input).value == "20"


@pytest.mark.anyio
async def test_topk_continue_advances_to_source_panel(tmp_path):
    app = make_app(tmp_path)
    state = app.engine.create_run("dock_topk_continue")
    state.current_step = Step.DOCKING_SELECTION
    state.candidates = [
        CandidateSequence(sequence=f"ACGT{i:02d}", candidate_id=f"cand-{i}")
        for i in range(1, 11)
    ]
    app.persistence.save(state)

    async with app.run_test() as pilot:
        await pilot.pause()
        _attach_fake_adapters(app)
        app.set_run_id("dock_topk_continue")
        app.push_screen("chat")
        await pilot.pause()
        await pilot.pause()

        strategy_panel = app.screen.query_one(DockingStrategyPanel)
        strategy_panel.query_one("#dock-plan-top-k", Input).value = "3"
        strategy_panel.query_one("#btn-dock-plan-continue", Button).focus()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        await pilot.pause()

        assert app.current_state.context.docking_recommendation.recommended_top_k == 3
        source_panel = app.screen.query_one(DockingSourcePanel)
        assert source_panel.top_k == 3


@pytest.mark.anyio
async def test_manual_upload_loads_per_candidate_receptors(tmp_path):
    app = make_app(tmp_path)
    state = app.engine.create_run("dock_manual_load")
    state.current_step = Step.DOCKING_SELECTION
    state.candidates = [
        CandidateSequence(sequence="ACGTACGT", candidate_id="cand-1"),
        CandidateSequence(sequence="ACGTACGT", candidate_id="cand-2"),
    ]
    app.persistence.save(state)

    structures_dir = tmp_path / "structures"
    structures_dir.mkdir()
    (structures_dir / "cand-1.pdbqt").write_text("FAKE\n", encoding="utf-8")
    (structures_dir / "cand-2.pdbqt").write_text("FAKE\n", encoding="utf-8")

    async with app.run_test() as pilot:
        await pilot.pause()
        _attach_fake_adapters(app)
        app.set_run_id("dock_manual_load")
        app.push_screen("chat")
        await pilot.pause()
        await pilot.pause()

        strategy_panel = app.screen.query_one(DockingStrategyPanel)
        strategy_panel.query_one("#dock-plan-top-k", Input).value = "2"
        strategy_panel.query_one("#btn-dock-plan-continue", Button).focus()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()

        source_panel = app.screen.query_one(DockingSourcePanel)
        source_panel.query_one("#btn-source-manual", Button).focus()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()

        upload_panel = app.screen.query_one(DockingManualUploadPanel)
        upload_panel.query_one("#dock-structures-dir", Input).value = str(structures_dir)
        upload_panel.query_one("#btn-load-structures", Button).focus()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()

        plan = app.current_state.docking_plan
        assert plan is not None
        assert set(plan.receptor_paths.keys()) == {"cand-1", "cand-2"}
        assert all(isinstance(box, GridBox) for box in plan.grid_boxes.values())
        # final phase is editing_form (DockingParamPanel shown)
        app.screen.query_one(DockingParamPanel)


@pytest.mark.anyio
async def test_rnacomposer_auto_path_prepares_receptors(tmp_path):
    app = make_app(tmp_path)
    state = app.engine.create_run("dock_rnacomposer")
    state.current_step = Step.DOCKING_SELECTION
    state.candidates = [
        CandidateSequence(sequence="ACGTACGT", candidate_id="cand-1"),
        CandidateSequence(sequence="ACGTACGT", candidate_id="cand-2"),
    ]
    app.persistence.save(state)

    async with app.run_test() as pilot:
        await pilot.pause()
        prep, rna = _attach_fake_adapters(app)
        app.set_run_id("dock_rnacomposer")
        app.push_screen("chat")
        await pilot.pause()
        await pilot.pause()

        strategy_panel = app.screen.query_one(DockingStrategyPanel)
        strategy_panel.query_one("#dock-plan-top-k", Input).value = "2"
        strategy_panel.query_one("#btn-dock-plan-continue", Button).focus()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()

        source_panel = app.screen.query_one(DockingSourcePanel)
        source_panel.query_one("#btn-source-rnacomposer", Button).focus()
        await pilot.pause()
        await pilot.press("enter")
        # Worker spawns; allow it to finish.
        for _ in range(40):
            if app.current_state.docking_plan is not None:
                break
            await pilot.pause()

        plan = app.current_state.docking_plan
        assert plan is not None
        assert plan.receptor_source == "rnacomposer"
        assert set(plan.receptor_paths.keys()) == {"cand-1", "cand-2"}
        assert rna.calls == ["ACGUACGU", "ACGUACGU"]


class _FailingFetchAdapter(FakeRNAComposerAdapter):
    """Succeeds on all candidates except cand-1."""

    def predict_to_path(
        self,
        sequence: str,
        secondary_structure: str = "",
        output_dir: str | Path = ".",
        *,
        candidate_id: str | None = None,
        on_poll: Any = None,
    ) -> str:
        if candidate_id == "cand-1":
            self.calls.append(sequence)
            raise RuntimeError("server error")
        return super().predict_to_path(
            sequence,
            secondary_structure=secondary_structure,
            output_dir=output_dir,
            candidate_id=candidate_id,
            on_poll=on_poll,
        )


async def _navigate_to_rnacomposer(pilot, app, *, top_k: str = "3") -> None:
    """Advance strategy → source → RNAComposer and wait for docking_plan."""
    strategy_panel = app.screen.query_one(DockingStrategyPanel)
    strategy_panel.query_one("#dock-plan-top-k", Input).value = top_k
    strategy_panel.query_one("#btn-dock-plan-continue", Button).focus()
    await pilot.pause()
    await pilot.press("enter")
    await pilot.pause()
    await pilot.pause()

    source_panel = app.screen.query_one(DockingSourcePanel)
    source_panel.query_one("#btn-source-rnacomposer", Button).focus()
    await pilot.pause()
    await pilot.press("enter")
    for _ in range(60):
        if (
            app.current_state.docking_plan is not None
            and app.current_state.docking_plan.receptor_source == "rnacomposer"
        ):
            break
        await pilot.pause()


@pytest.mark.anyio
async def test_rnacomposer_pipeline_with_3_candidates(tmp_path):
    """Pipeline should fetch and post-process all candidates."""
    app = make_app(tmp_path)
    state = app.engine.create_run("dock_pipeline3")
    state.current_step = Step.DOCKING_SELECTION
    state.candidates = [
        CandidateSequence(sequence="ACGTACGT", candidate_id=f"cand-{i}")
        for i in range(3)
    ]
    app.persistence.save(state)

    async with app.run_test() as pilot:
        await pilot.pause()
        prep, rna = _attach_fake_adapters(app)
        app.set_run_id("dock_pipeline3")
        app.push_screen("chat")
        await pilot.pause()
        await pilot.pause()

        await _navigate_to_rnacomposer(pilot, app)

        plan = app.current_state.docking_plan
        assert plan is not None
        assert set(plan.receptor_paths.keys()) == {"cand-0", "cand-1", "cand-2"}
        assert len(rna.calls) == 3


@pytest.mark.anyio
async def test_rnacomposer_pipeline_partial_failure(tmp_path):
    """Pipeline should continue when one candidate fetch fails."""
    app = make_app(tmp_path)
    state = app.engine.create_run("dock_partial_fail")
    state.current_step = Step.DOCKING_SELECTION
    state.candidates = [
        CandidateSequence(sequence="ACGTACGT", candidate_id="cand-0"),
        CandidateSequence(sequence="ACGTACGT", candidate_id="cand-1"),
        CandidateSequence(sequence="ACGTACGT", candidate_id="cand-2"),
    ]
    app.persistence.save(state)

    async with app.run_test() as pilot:
        await pilot.pause()
        prep = FakeReceptorPrepAdapter()
        rna = _FailingFetchAdapter()
        app.receptor_prep_adapter = prep
        app.tertiary_structure_adapter = rna
        app.set_run_id("dock_partial_fail")
        app.push_screen("chat")
        await pilot.pause()
        await pilot.pause()

        await _navigate_to_rnacomposer(pilot, app)

        plan = app.current_state.docking_plan
        assert plan is not None
        assert set(plan.receptor_paths.keys()) == {"cand-0", "cand-2"}
        assert len(rna.calls) == 3


@pytest.mark.anyio
async def test_param_panel_is_readonly_confirmation(tmp_path):
    """Phase 4 panel must NOT expose editable numeric inputs anymore."""

    app = make_app(tmp_path)
    state = app.engine.create_run("dock_param_readonly")
    state.current_step = Step.DOCKING_SELECTION
    state.candidates = [
        CandidateSequence(sequence="ACGT", candidate_id="cand-1"),
    ]
    state.docking_plan = DockingPlan(
        machine_profile={"cpu_count": 4},
        recommended_top_k=1,
        receptor_paths={"cand-1": "/tmp/cand-1.pdbqt"},
        grid_boxes={"cand-1": GridBox(center=[1.0, 2.0, 3.0], size=[20.0, 20.0, 20.0])},
        receptor_source="manual",
        exhaustiveness=16,
        num_modes=12,
        energy_range=2.5,
        grid_padding_angstrom=5.0,
        per_ligand_timeout_seconds=2400,
        seed=42,
    )
    state.context.docking_recommendation.phase = "structures_ready"
    state.context.docking_recommendation.recommended_top_k = 1
    app.persistence.save(state)

    async with app.run_test() as pilot:
        await pilot.pause()
        _attach_fake_adapters(app)
        app.set_run_id("dock_param_readonly")
        app.push_screen("chat")
        await pilot.pause()
        await pilot.pause()

        panel = app.screen.query_one(DockingParamPanel)
        with pytest.raises(NoMatches):
            panel.query_one("#dock-time-budget", Input)
        with pytest.raises(NoMatches):
            panel.query_one("#dock-exhaustiveness", Input)
        with pytest.raises(NoMatches):
            panel.query_one("#dock-padding", Input)


@pytest.mark.anyio
async def test_param_panel_submit_preserves_plan_and_advances(tmp_path):
    app = make_app(tmp_path)
    state = app.engine.create_run("dock_param_submit")
    state.current_step = Step.DOCKING_SELECTION
    state.candidates = [
        CandidateSequence(sequence="ACGT", candidate_id="cand-1"),
    ]
    state.docking_plan = DockingPlan(
        machine_profile={"cpu_count": 4},
        recommended_top_k=1,
        receptor_paths={"cand-1": "/tmp/cand-1.pdbqt"},
        grid_boxes={"cand-1": GridBox(center=[1.0, 2.0, 3.0], size=[20.0, 20.0, 20.0])},
        receptor_source="manual",
        exhaustiveness=16,
        num_modes=12,
        energy_range=2.5,
        per_ligand_timeout_seconds=2400,
        time_budget=6,
        seed=42,
    )
    state.context.docking_recommendation.phase = "structures_ready"
    state.context.docking_recommendation.recommended_top_k = 1
    app.persistence.save(state)

    async with app.run_test() as pilot:
        await pilot.pause()
        _attach_fake_adapters(app)
        app.set_run_id("dock_param_submit")
        app.push_screen("chat")
        await pilot.pause()
        await pilot.pause()

        panel = app.screen.query_one(DockingParamPanel)
        panel.query_one("#btn-submit-dock", Button).focus()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()

        plan = app.current_state.docking_plan
        # Values set in Phase 1 must survive the read-only confirmation.
        assert plan.exhaustiveness == 16
        assert plan.num_modes == 12
        assert plan.energy_range == 2.5
        assert plan.per_ligand_timeout_seconds == 2400
        assert plan.time_budget == 6
        assert plan.seed == 42
        assert app.current_state.current_step == Step.DOCKING_RUN


@pytest.mark.anyio
async def test_strategy_panel_persists_all_params(tmp_path):
    """Phase 1 form must write every Vina knob into ``state.docking_plan``."""

    app = make_app(tmp_path)
    state = app.engine.create_run("dock_strategy_full")
    state.current_step = Step.DOCKING_SELECTION
    state.candidates = [
        CandidateSequence(sequence=f"ACGT{i:02d}", candidate_id=f"cand-{i}")
        for i in range(1, 11)
    ]
    app.persistence.save(state)

    async with app.run_test() as pilot:
        await pilot.pause()
        _attach_fake_adapters(app)
        app.set_run_id("dock_strategy_full")
        app.push_screen("chat")
        await pilot.pause()
        await pilot.pause()

        strategy_panel = app.screen.query_one(DockingStrategyPanel)
        strategy_panel.query_one("#dock-plan-top-k", Input).value = "4"
        strategy_panel.query_one("#dock-plan-exhaustiveness", Input).value = "16"
        strategy_panel.query_one("#dock-plan-num-modes", Input).value = "12"
        strategy_panel.query_one("#dock-plan-energy-range", Input).value = "2.5"
        strategy_panel.query_one("#dock-plan-padding", Input).value = "5.0"
        strategy_panel.query_one(
            "#dock-plan-per-ligand-timeout", Input
        ).value = "2400"
        strategy_panel.query_one("#dock-plan-time-budget", Input).value = "6"
        strategy_panel.query_one("#dock-plan-seed", Input).value = "42"
        strategy_panel.query_one("#btn-dock-plan-continue", Button).focus()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        await pilot.pause()

        plan = app.current_state.docking_plan
        assert plan is not None
        assert plan.recommended_top_k == 4
        assert plan.exhaustiveness == 16
        assert plan.num_modes == 12
        assert plan.energy_range == 2.5
        assert plan.grid_padding_angstrom == 5.0
        assert plan.per_ligand_timeout_seconds == 2400
        assert plan.time_budget == 6
        assert plan.seed == 42

        rec = app.current_state.context.docking_recommendation
        assert rec.recommended_top_k == 4
        assert rec.recommended_exhaustiveness == 16
        assert rec.recommended_num_modes == 12
        assert rec.recommended_energy_range == 2.5
        assert rec.recommended_per_ligand_timeout_seconds == 2400


@pytest.mark.anyio
async def test_strategy_panel_clamps_out_of_range_inputs(tmp_path):
    """Out-of-range form values must be clamped (not blindly accepted)."""

    app = make_app(tmp_path)
    state = app.engine.create_run("dock_strategy_clamp")
    state.current_step = Step.DOCKING_SELECTION
    state.candidates = [
        CandidateSequence(sequence=f"ACGT{i:02d}", candidate_id=f"cand-{i}")
        for i in range(1, 4)
    ]
    app.persistence.save(state)

    async with app.run_test() as pilot:
        await pilot.pause()
        _attach_fake_adapters(app)
        app.set_run_id("dock_strategy_clamp")
        app.push_screen("chat")
        await pilot.pause()
        await pilot.pause()

        strategy_panel = app.screen.query_one(DockingStrategyPanel)
        # top_k > candidate_count gets clamped to candidate_count
        strategy_panel.query_one("#dock-plan-top-k", Input).value = "99"
        # exhaustiveness not in {8,16,32} -> ignored, fallback applies
        strategy_panel.query_one("#dock-plan-exhaustiveness", Input).value = "7"
        # num_modes out of [1,20] -> clamped to 20
        strategy_panel.query_one("#dock-plan-num-modes", Input).value = "999"
        # energy_range out of [0.5, 10] -> clamped to 10
        strategy_panel.query_one("#dock-plan-energy-range", Input).value = "20.0"
        strategy_panel.query_one("#btn-dock-plan-continue", Button).focus()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        await pilot.pause()

        plan = app.current_state.docking_plan
        assert plan is not None
        assert plan.recommended_top_k == 3
        # Exhaustiveness 7 was ignored: panel default (8) should be kept.
        assert plan.exhaustiveness == 8
        assert plan.num_modes == 20
        assert plan.energy_range == 10.0


class _StubNlSkill:
    """Stub for DockingParamsParseSkill that returns a canned dict."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def parse(self, text: str, *, current_params=None, candidate_count=None):
        return dict(self._payload)


@pytest.mark.anyio
async def test_nl_parse_shows_confirm_only_panel(
    tmp_path, monkeypatch
):
    """NL input \u2192 planner \u2192 confirm_only pre-filled panel (no auto-submit)."""

    app = make_app(tmp_path)
    state = app.engine.create_run("dock_nl_parse")
    state.current_step = Step.DOCKING_SELECTION
    state.candidates = [
        CandidateSequence(sequence=f"ACGT{i:02d}", candidate_id=f"cand-{i}")
        for i in range(1, 11)
    ]
    app.persistence.save(state)

    class _StubPlannerSkill:
        """Stub for DockingPlannerSkill that returns a canned plan."""
        def plan(self, **kwargs):
            return {
                "recommended_top_k": 8,
                "recommended_exhaustiveness": 32,
                "recommended_num_modes": 15,
                "recommended_seed": 42,
                "reason": "stub reason",
                "receptor_path_note": "stub receptor note",
                "grid_center_note": "stub grid note",
            }

    async with app.run_test() as pilot:
        await pilot.pause()
        _attach_fake_adapters(app)
        app.set_run_id("dock_nl_parse")
        original = app.runtime.create_skill

        def _fake_create_skill(cls):
            if cls.__name__ == "DockingPlannerSkill":
                return _StubPlannerSkill()
            return original(cls)

        object.__setattr__(app.runtime, "create_skill", _fake_create_skill)

        app.push_screen("chat")
        await pilot.pause()
        await pilot.pause()

        handler = app.screen._handler
        assert handler is not None
        handler.handle_user_input(
            "top 8, exhaustiveness 32, seed 42, num_modes 15"
        )
        # Wait for the confirm_only panel to appear
        for _ in range(80):
            panel = None
            try:
                panel = app.screen.query_one(DockingStrategyPanel)
                if panel.confirm_only:
                    break
            except NoMatches:
                pass
            await pilot.pause()

        confirm_panel = app.screen.query_one(DockingStrategyPanel)
        assert confirm_panel.confirm_only is True
        assert confirm_panel.query_one("#dock-plan-top-k", Input).value == "8"
        assert (
            confirm_panel.query_one("#dock-plan-exhaustiveness", Input).value
            == "32"
        )
        assert confirm_panel.query_one("#dock-plan-num-modes", Input).value == "15"
        assert confirm_panel.query_one("#dock-plan-seed", Input).value == "42"

        # Should NOT have advanced to the source panel.
        with pytest.raises(NoMatches):
            app.screen.query_one(DockingSourcePanel)
        # State.docking_plan should not have been written yet.
        assert app.current_state.docking_plan is None


@pytest.mark.anyio
async def test_strategy_panel_apply_overrides_helper(tmp_path):
    """``apply_overrides`` must write each known key into the Input widgets."""

    app = make_app(tmp_path)
    state = app.engine.create_run("dock_apply_overrides")
    state.current_step = Step.DOCKING_SELECTION
    state.candidates = [
        CandidateSequence(sequence=f"ACGT{i:02d}", candidate_id=f"cand-{i}")
        for i in range(1, 6)
    ]
    app.persistence.save(state)

    async with app.run_test() as pilot:
        await pilot.pause()
        _attach_fake_adapters(app)
        app.set_run_id("dock_apply_overrides")
        app.push_screen("chat")
        await pilot.pause()
        await pilot.pause()

        panel = app.screen.query_one(DockingStrategyPanel)
        applied = panel.apply_overrides(
            {
                "top_k": 3,
                "exhaustiveness": 16,
                "seed": 7,
                "energy_range": 4.5,
                "unknown_key": "ignored",
            }
        )
        await pilot.pause()
        assert set(applied) == {"top_k", "exhaustiveness", "seed", "energy_range"}
        assert panel.query_one("#dock-plan-top-k", Input).value == "3"
        assert panel.query_one("#dock-plan-exhaustiveness", Input).value == "16"
        assert panel.query_one("#dock-plan-seed", Input).value == "7"
        assert panel.query_one("#dock-plan-energy-range", Input).value == "4.5"


# ---------------------------------------------------------------------------
# Mutation ratio filter integration tests
# ---------------------------------------------------------------------------

from aptgent.domain.models import Mutation
from aptgent.tui.widgets.structured_input import MutationRatioPanel


def _make_candidates_with_mutations() -> list[CandidateSequence]:
    """4 candidates with varying mutation coverage over sites [2, 5, 8]."""
    return [
        CandidateSequence(
            sequence="ACGTACGTAC",
            candidate_id="full",
            mutations=[
                Mutation(position=2, original="G", mutated="A"),
                Mutation(position=5, original="T", mutated="C"),
                Mutation(position=8, original="A", mutated="G"),
            ],
        ),
        CandidateSequence(
            sequence="ACGTACGTAC",
            candidate_id="partial",
            mutations=[
                Mutation(position=2, original="G", mutated="A"),
                Mutation(position=5, original="T", mutated="C"),
            ],
        ),
        CandidateSequence(
            sequence="ACGTACGTAC",
            candidate_id="one",
            mutations=[
                Mutation(position=2, original="G", mutated="A"),
            ],
        ),
        CandidateSequence(
            sequence="ACGTACGTAC",
            candidate_id="none",
            mutations=[],
        ),
    ]


@pytest.mark.anyio
async def test_strategy_continue_shows_filter_panel(tmp_path):
    """After strategy submit with confirmed sites, filter panel appears."""
    app = make_app(tmp_path)
    state = app.engine.create_run("filter_appear")
    state.current_step = Step.DOCKING_SELECTION
    state.candidates = _make_candidates_with_mutations()
    state.confirmed_mutation_sites = [2, 5, 8]
    app.persistence.save(state)

    async with app.run_test() as pilot:
        await pilot.pause()
        _attach_fake_adapters(app)
        app.set_run_id("filter_appear")
        app.push_screen("chat")
        await pilot.pause()
        await pilot.pause()

        # Submit strategy form → should advance to filter panel
        strategy = app.screen.query_one(DockingStrategyPanel)
        strategy.query_one("#btn-dock-plan-continue", Button).focus()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        await pilot.pause()

        # Filter panel should be visible (not source panel)
        filter_panel = app.screen.query_one(MutationRatioPanel)
        assert filter_panel.total_count == 4


@pytest.mark.anyio
async def test_filter_skip_shows_source_panel(tmp_path):
    """Skip on filter panel routes to source panel."""
    app = make_app(tmp_path)
    state = app.engine.create_run("filter_skip")
    state.current_step = Step.DOCKING_SELECTION
    state.candidates = _make_candidates_with_mutations()
    state.confirmed_mutation_sites = [2, 5, 8]
    app.persistence.save(state)

    async with app.run_test() as pilot:
        await pilot.pause()
        _attach_fake_adapters(app)
        app.set_run_id("filter_skip")
        app.push_screen("chat")
        await pilot.pause()
        await pilot.pause()

        # Submit strategy
        strategy = app.screen.query_one(DockingStrategyPanel)
        strategy.query_one("#btn-dock-plan-continue", Button).focus()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        await pilot.pause()

        # Now on filter panel — click Skip
        filter_panel = app.screen.query_one(MutationRatioPanel)
        filter_panel.query_one("#btn-mutation-ratio-skip", Button).focus()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()

        # Should now be on source panel with all 4 candidates
        source = app.screen.query_one(DockingSourcePanel)
        assert source.top_k == 4


@pytest.mark.anyio
async def test_filter_skipped_when_no_confirmed_sites(tmp_path):
    """Auto-skips filter when no confirmed_mutation_sites."""
    app = make_app(tmp_path)
    state = app.engine.create_run("filter_no_sites")
    state.current_step = Step.DOCKING_SELECTION
    state.candidates = [
        CandidateSequence(sequence="ACGTACGT", candidate_id=f"c{i}")
        for i in range(5)
    ]
    # No confirmed_mutation_sites → filter should be skipped
    app.persistence.save(state)

    async with app.run_test() as pilot:
        await pilot.pause()
        _attach_fake_adapters(app)
        app.set_run_id("filter_no_sites")
        app.push_screen("chat")
        await pilot.pause()
        await pilot.pause()

        strategy = app.screen.query_one(DockingStrategyPanel)
        strategy.query_one("#btn-dock-plan-continue", Button).focus()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        await pilot.pause()

        # Should go straight to source panel (no filter panel)
        source = app.screen.query_one(DockingSourcePanel)
        assert source.top_k == 5
