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
async def test_param_panel_submit_advances_to_docking_run(tmp_path):
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
        panel.query_one("#dock-time-budget", Input).value = "6"
        panel.query_one("#dock-exhaustiveness", Input).value = "16"
        panel.query_one("#btn-submit-dock", Button).focus()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()

        plan = app.current_state.docking_plan
        assert plan.exhaustiveness == 16
        assert plan.time_budget == 6
        assert app.current_state.current_step == Step.DOCKING_RUN
