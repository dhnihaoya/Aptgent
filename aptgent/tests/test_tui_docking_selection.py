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
    TargetMolecule,
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

    def compute_box(self, path: str | Path, *, padding: float = 4.0) -> BoundingBox:
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
        assert panel.query_one("#dock-plan-top-k", Input).value == "5"


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


@pytest.mark.anyio
async def test_skipping_docking_clears_plan_and_reaches_final_report(tmp_path):
    app = make_app(tmp_path)
    state = app.engine.create_run("dock_skip_case")
    state.current_step = Step.DOCKING_SELECTION
    state.target_molecule = TargetMolecule(
        input_text="caffeine",
        resolved_name="Caffeine",
        smiles="Cn1cnc2n(C)c(=O)n(C)c(=O)c12",
        resolution_status="resolved",
    )
    state.candidates = [
        CandidateSequence(sequence=f"ACGT{i:02d}", candidate_id=f"cand-{i}")
        for i in range(1, 4)
    ]
    app.persistence.save(state)

    async with app.run_test() as pilot:
        await pilot.pause()
        _attach_fake_adapters(app)
        app.set_run_id("dock_skip_case")
        app.push_screen("chat")
        await pilot.pause()
        await pilot.pause()

        strategy_panel = app.screen.query_one(DockingStrategyPanel)
        strategy_panel.query_one("#btn-dock-plan-skip", Button).focus()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        await pilot.pause()

        assert app.current_state.docking_plan is None
        assert app.current_state.docking_results == []
        assert app.current_state.context.docking_recommendation.strategy == "skipped"
        assert app.current_state.context.docking_recommendation.phase == "skipped"
        assert app.current_state.current_step == Step.FINAL_REPORT


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
async def test_nl_parse_fills_strategy_panel_without_submitting(
    tmp_path, monkeypatch
):
    """Natural language overrides must fill the form, not auto-submit."""

    app = make_app(tmp_path)
    state = app.engine.create_run("dock_nl_parse")
    state.current_step = Step.DOCKING_SELECTION
    state.candidates = [
        CandidateSequence(sequence=f"ACGT{i:02d}", candidate_id=f"cand-{i}")
        for i in range(1, 11)
    ]
    app.persistence.save(state)

    stub = _StubNlSkill(
        {"top_k": 8, "exhaustiveness": 32, "seed": 42, "num_modes": 15}
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        _attach_fake_adapters(app)
        app.set_run_id("dock_nl_parse")
        # Patch the runtime skill factory to return our stub for the NL skill
        original = app.runtime.create_skill

        def _fake_create_skill(cls):
            if cls.__name__ == "DockingParamsParseSkill":
                return stub
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
        # let worker finish
        for _ in range(40):
            if app.screen.query_one("#dock-plan-top-k", Input).value == "8":
                break
            await pilot.pause()

        strategy_panel = app.screen.query_one(DockingStrategyPanel)
        assert strategy_panel.query_one("#dock-plan-top-k", Input).value == "8"
        assert (
            strategy_panel.query_one("#dock-plan-exhaustiveness", Input).value
            == "32"
        )
        assert strategy_panel.query_one("#dock-plan-num-modes", Input).value == "15"
        assert strategy_panel.query_one("#dock-plan-seed", Input).value == "42"

        # Should NOT have advanced to the source panel.
        with pytest.raises(NoMatches):
            app.screen.query_one(DockingSourcePanel)
        # State.docking_plan should not have been written yet.
        assert app.current_state.docking_plan is None


@pytest.mark.anyio
async def test_nl_parse_skip_action_short_circuits_to_skip(
    tmp_path, monkeypatch
):
    app = make_app(tmp_path)
    state = app.engine.create_run("dock_nl_skip")
    state.current_step = Step.DOCKING_SELECTION
    state.target_molecule = TargetMolecule(
        input_text="caffeine",
        resolved_name="Caffeine",
        smiles="Cn1cnc2n(C)c(=O)n(C)c(=O)c12",
        resolution_status="resolved",
    )
    state.candidates = [
        CandidateSequence(sequence=f"ACGT{i:02d}", candidate_id=f"cand-{i}")
        for i in range(1, 4)
    ]
    app.persistence.save(state)

    stub = _StubNlSkill({"action": "skip"})

    async with app.run_test() as pilot:
        await pilot.pause()
        _attach_fake_adapters(app)
        app.set_run_id("dock_nl_skip")
        original = app.runtime.create_skill

        def _fake_create_skill(cls):
            if cls.__name__ == "DockingParamsParseSkill":
                return stub
            return original(cls)

        object.__setattr__(app.runtime, "create_skill", _fake_create_skill)
        app.push_screen("chat")
        await pilot.pause()
        await pilot.pause()

        handler = app.screen._handler
        assert handler is not None
        handler.handle_user_input("\u8df3\u8fc7 docking")  # "skip docking" in zh
        for _ in range(40):
            if app.current_state.context.docking_recommendation.strategy == "skipped":
                break
            await pilot.pause()

        assert app.current_state.docking_plan is None
        assert (
            app.current_state.context.docking_recommendation.strategy == "skipped"
        )


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
