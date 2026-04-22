from __future__ import annotations

import pytest

from aptgent.domain.enums import Step
from aptgent.domain.models import CandidateSequence, TargetMolecule
from aptgent.tui.widgets.structured_input import DockingParamPanel, DockingStrategyPanel
from textual.css.query import NoMatches
from textual.widgets import Button, Input, OptionList

from tui_helpers import anyio_backend, make_app


@pytest.mark.anyio
async def test_docking_recommendation_requires_accept_or_customize_before_form(tmp_path, monkeypatch):
    class FakeDockingPlannerSkill:
        def explain_plan_stream(self, **kwargs):
            yield "### Recommended Docking Setup\n"
            yield "- Time budget: **4 hour(s)**\n"
            yield "- Suggested batch: **top 12**\n"
            yield "- Suggested grid box size: **22.0, 24.0, 20.0**\n"

        def plan(self, **kwargs):
            return {
                "recommended_time_budget_hours": 4,
                "recommended_top_k": 12,
                "recommended_grid_size": [22.0, 24.0, 20.0],
                "receptor_path_note": "Provide the receptor path manually.",
                "grid_center_note": "Confirm the grid center from the binding site.",
                "reason": "Fits the available CPU budget.",
            }

    class FakeHardwareProbeAdapter:
        def probe(self):
            return {"cpu_count": 8, "memory_gb": 32}

    monkeypatch.setattr(
        "aptgent.tui.steps.docking_selection.DockingPlannerSkill",
        FakeDockingPlannerSkill,
    )
    monkeypatch.setattr(
        "aptgent.tui.steps.docking_selection.HardwareProbeAdapter",
        FakeHardwareProbeAdapter,
    )

    app = make_app(tmp_path)
    state = app.engine.create_run("dock_reco_case")
    state.current_step = Step.DOCKING_SELECTION
    state.candidates = [
        CandidateSequence(sequence=f"ACGT{i:02d}", candidate_id=f"cand-{i}")
        for i in range(1, 21)
    ]
    app.persistence.save(state)

    async with app.run_test() as pilot:
        await pilot.pause()
        app.set_run_id("dock_reco_case")
        app.push_screen("chat")
        await pilot.pause()
        await pilot.pause()

        strategy_panel = app.screen.query_one(DockingStrategyPanel)
        strategy_panel.query_one("#dock-plan-budget", Input).value = "4"
        strategy_panel.query_one("#btn-dock-plan-llm", Button).focus()

        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()

        recommendation_menu = app.screen.query_one("#action-menu", OptionList)
        assert recommendation_menu.get_option_at_index(0).id == "accept-docking-recommendation"
        assert app.current_state.context.docking_recommendation.recommended_time_budget_hours == 4
        assert app.current_state.context.docking_recommendation.recommended_top_k == 12
        assert app.current_state.context.docking_recommendation.recommended_grid_size == [22.0, 24.0, 20.0]
        assert "Suggested grid box size" in app.current_state.context.docking_recommendation.display_markdown
        with pytest.raises(NoMatches):
            app.screen.query_one(DockingParamPanel)
@pytest.mark.anyio
async def test_accepting_docking_recommendation_prefills_compact_form(tmp_path, monkeypatch):
    class FakeDockingPlannerSkill:
        def explain_plan_stream(self, **kwargs):
            yield "Recommendation"

        def plan(self, **kwargs):
            return {
                "recommended_time_budget_hours": 4,
                "recommended_top_k": 12,
                "recommended_grid_size": [22.0, 24.0, 20.0],
                "receptor_path_note": "Provide the receptor path manually.",
                "grid_center_note": "Confirm the grid center from the binding site.",
                "reason": "Fits the available CPU budget.",
            }

    class FakeHardwareProbeAdapter:
        def probe(self):
            return {"cpu_count": 8, "memory_gb": 32}

    monkeypatch.setattr(
        "aptgent.tui.steps.docking_selection.DockingPlannerSkill",
        FakeDockingPlannerSkill,
    )
    monkeypatch.setattr(
        "aptgent.tui.steps.docking_selection.HardwareProbeAdapter",
        FakeHardwareProbeAdapter,
    )

    app = make_app(tmp_path)
    state = app.engine.create_run("dock_accept_case")
    state.current_step = Step.DOCKING_SELECTION
    state.time_budget = 4
    state.candidates = [
        CandidateSequence(sequence=f"ACGT{i:02d}", candidate_id=f"cand-{i}")
        for i in range(1, 16)
    ]
    app.persistence.save(state)

    async with app.run_test() as pilot:
        await pilot.pause()
        app.set_run_id("dock_accept_case")
        app.push_screen("chat")
        await pilot.pause()
        await pilot.pause()

        strategy_panel = app.screen.query_one(DockingStrategyPanel)
        strategy_panel.query_one("#btn-dock-plan-llm", Button).focus()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        app.screen.query_one("#action-menu", OptionList).focus()
        await pilot.press("enter")
        await pilot.pause()

        panel = app.screen.query_one(DockingParamPanel)
        assert panel.mode == "llm"
        assert panel.accepted_recommendation is True
        assert panel.recommended_top_k == 12
        assert panel.query_one("#dock-time-budget", Input).value == "4"
        assert panel.query_one("#dock-top-k", Input).value == "12"
        assert panel.query_one("#dock-sx", Input).value == "22.0"
        assert panel.query_one("#dock-receptor") is not None
@pytest.mark.anyio
async def test_manual_docking_path_opens_editable_form_directly(tmp_path):
    app = make_app(tmp_path)
    state = app.engine.create_run("dock_manual_case")
    state.current_step = Step.DOCKING_SELECTION
    state.time_budget = 6
    state.candidates = [
        CandidateSequence(sequence=f"ACGT{i:02d}", candidate_id=f"cand-{i}")
        for i in range(1, 8)
    ]
    app.persistence.save(state)

    async with app.run_test() as pilot:
        await pilot.pause()
        app.set_run_id("dock_manual_case")
        app.push_screen("chat")
        await pilot.pause()
        await pilot.pause()

        strategy_panel = app.screen.query_one(DockingStrategyPanel)
        strategy_panel.query_one("#btn-dock-plan-manual", Button).focus()
        await pilot.press("enter")
        await pilot.pause()

        panel = app.screen.query_one(DockingParamPanel)
        assert panel.mode == "manual"
        assert panel.query_one("#dock-time-budget", Input).value == "6"
        assert panel.query_one("#dock-top-k", Input).value == ""
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
        app.set_run_id("dock_skip_case")
        app.push_screen("chat")
        await pilot.pause()
        await pilot.pause()

        strategy_panel = app.screen.query_one(DockingStrategyPanel)
        strategy_panel.query_one("#btn-dock-plan-skip", Button).focus()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        await pilot.pause()

        assert app.current_state.docking_plan is None
        assert app.current_state.docking_results == []
        assert app.current_state.context.docking_recommendation.strategy == "skipped"
        assert app.current_state.context.docking_recommendation.phase == "skipped"
        assert app.current_state.current_step == Step.FINAL_REPORT
