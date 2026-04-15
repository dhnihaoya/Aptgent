from __future__ import annotations

import asyncio

import pytest

from aptgent.domain.enums import Step
from aptgent.domain.models import CandidateSequence, SecondaryStructure, TargetMolecule
from aptgent.tui.app import AptgentApp
from aptgent.tui.screens.quit_confirm import QuitConfirmScreen
from aptgent.tui.screens.resume import _overview, _timestamp_label
from aptgent.tui.screens.theme_picker import ThemePickerScreen
from aptgent.tui.widgets.chat_widgets import ActivityBubble, InputBar, ThinkingBubble
from aptgent.tui.widgets.structured_input import (
    ActionMenuPanel,
    DockingParamPanel,
    DockingStrategyPanel,
    MutationSitePanel,
)
from textual.css.query import NoMatches
from textual.widgets import Button, Input, OptionList


class FakeRNAFoldAdapter:
    def fold(self, sequence: str) -> SecondaryStructure:
        return SecondaryStructure(
            sequence=sequence,
            dot_bracket="." * len(sequence),
            mfe=-1.0,
        )


class FakePredictionAdapter:
    def predict_batch(self, candidates, target):
        return []

    def predict_batch_for_targets(self, candidates, targets):
        return {target.smiles or target.input_text: [] for target in targets}


class FakeVinaAdapter:
    def run_batch(self, **kwargs):
        return []


class FakeResolver:
    def resolve(self, text: str) -> TargetMolecule:
        return TargetMolecule(
            input_text=text,
            resolved_name=text,
            smiles="C1=CC=CC=C1",
            resolution_status="resolved",
        )


class FakeSpatialRankAdapter:
    def rank_batch(self, candidates, target):
        return []


def make_app(tmp_path) -> AptgentApp:
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
    return AptgentApp(
        config={
            "paths": {"runs_dir": str(tmp_path / "runs")},
            "enumeration": {"max_candidates": 5000},
        },
        tools_config={},
        rna_fold_adapter=FakeRNAFoldAdapter(),
        prediction_adapter=FakePredictionAdapter(),
        vina_adapter=FakeVinaAdapter(),
        molecule_resolver=FakeResolver(),
        spatial_rank_adapter=FakeSpatialRankAdapter(),
    )


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_app_registers_only_main_screens():
    assert set(AptgentApp.SCREENS) == {"welcome", "chat"}


def test_set_run_id_restores_saved_progress(tmp_path):
    app = make_app(tmp_path)
    state = app.engine.create_run("resume_case")
    state.current_step = Step.PRIMARY_SCORING
    app.persistence.save(state)

    app.set_run_id("resume_case")

    assert app.current_state.current_step == Step.PRIMARY_SCORING
    assert app.progress_bar.current_step == Step.PRIMARY_SCORING


@pytest.mark.anyio
async def test_welcome_screen_is_default(tmp_path):
    app = make_app(tmp_path)

    async with app.run_test() as pilot:
        await pilot.pause()
        assert type(app.screen).__name__ == "WelcomeScreen"


@pytest.mark.anyio
async def test_welcome_screen_starts_without_active_run(tmp_path):
    app = make_app(tmp_path)

    async with app.run_test() as pilot:
        await pilot.pause()
        assert app._state is None
        assert app.persistence.list_runs() == []
        assert app.status_panel.run_id == ""
        assert app.theme == "textual-dark"


@pytest.mark.anyio
async def test_welcome_screen_has_chat_input_not_name_prompt(tmp_path):
    app = make_app(tmp_path)

    async with app.run_test() as pilot:
        await pilot.pause()

        chat_input = app.screen.query_one("#chat-input")
        assert app.screen.focused is chat_input
        assert app.screen.query_one("#welcome-wordmark") is not None
        assert app.screen.query_one("#welcome-logo") is not None
        with pytest.raises(NoMatches):
            app.screen.query_one("#new-run-input")
        with pytest.raises(NoMatches):
            app.screen.query_one("#btn-new-run")
        with pytest.raises(NoMatches):
            app.screen.query_one("#welcome-kicker")


@pytest.mark.anyio
async def test_first_message_creates_run_and_enters_chat_screen(tmp_path):
    app = make_app(tmp_path)

    async with app.run_test() as pilot:
        await pilot.pause()
        chat_input = app.screen.query_one("#chat-input")
        chat_input.value = "Design an aptamer for caffeine."

        await pilot.press("enter")
        await pilot.pause()

        assert type(app.screen).__name__ == "ChatScreen"
        assert app.current_state.current_step == Step.INTAKE
        assert app.screen._handler.__class__.__name__ == "IntakeHandler"
        assert len(app.persistence.list_runs()) == 1


@pytest.mark.anyio
async def test_slash_shows_command_palette_in_welcome(tmp_path):
    app = make_app(tmp_path)

    async with app.run_test() as pilot:
        await pilot.pause()
        chat_input = app.screen.query_one("#chat-input")
        chat_input.value = "/"
        await pilot.pause()

        input_bar = app.screen.query_one(InputBar)
        assert input_bar.command_palette_open()
        command_list = app.screen.query_one("#command-list", OptionList)
        assert len(command_list.options) == 3
        assert command_list.get_option_at_index(0).id == "/resume"
        assert command_list.get_option_at_index(1).id == "/quit"
        assert command_list.get_option_at_index(2).id == "/theme"


def test_resume_option_text_includes_overview_step_and_timestamp(tmp_path):
    app = make_app(tmp_path)
    state = app.engine.create_run("abc123def456")
    state.current_step = Step.PRIMARY_SCORING
    state.input_payload["initial_sequence"] = "ACGTACGTACGT"
    state.target_molecule = TargetMolecule(
        input_text="caffeine",
        resolved_name="Caffeine",
        smiles="Cn1cnc2n(C)c(=O)n(C)c(=O)c12",
        resolution_status="resolved",
    )
    state.updated_at = "2026-04-15T10:30:00+00:00"

    overview = _overview(state)
    timestamp = _timestamp_label(state)

    assert overview == "Caffeine | ACGTACGTACGT - Primary Scoring"
    assert timestamp.endswith(" - abc123def456")


@pytest.mark.anyio
async def test_resume_command_opens_picker_and_switches_run(tmp_path):
    app = make_app(tmp_path)

    resume_target = app.engine.create_run("resume_me")
    resume_target.current_step = Step.PRIMARY_SCORING
    resume_target.input_payload["initial_sequence"] = "ACGTACGT"
    resume_target.input_payload["target_molecule"] = "caffeine"
    app.persistence.save(resume_target)

    async with app.run_test() as pilot:
        await pilot.pause()
        chat_input = app.screen.query_one("#chat-input")
        chat_input.value = "/resume"
        chat_input.focus()

        await pilot.press("enter")
        await pilot.pause()

        assert type(app.screen).__name__ == "ResumePickerScreen"
        run_list = app.screen.query_one("#resume-run-list", OptionList)
        assert app.screen.focused is run_list

        await pilot.press("enter")
        await pilot.pause()

        assert type(app.screen).__name__ == "ChatScreen"
        assert app.current_state.run_id == "resume_me"
        assert app.current_state.current_step == Step.PRIMARY_SCORING


@pytest.mark.anyio
async def test_escape_closes_palette_before_opening_quit_modal(tmp_path):
    app = make_app(tmp_path)

    async with app.run_test() as pilot:
        await pilot.pause()
        chat_input = app.screen.query_one("#chat-input")
        chat_input.value = "/"
        await pilot.pause()

        input_bar = app.screen.query_one(InputBar)
        assert input_bar.command_palette_open()

        await pilot.press("escape")
        await pilot.pause()

        assert type(app.screen).__name__ == "WelcomeScreen"
        assert not input_bar.command_palette_open()

        await pilot.press("escape")
        await pilot.pause()

        assert isinstance(app.screen, QuitConfirmScreen)


@pytest.mark.anyio
async def test_ctrl_q_opens_quit_modal(tmp_path):
    app = make_app(tmp_path)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+q")
        await pilot.pause()

        assert isinstance(app.screen, QuitConfirmScreen)


@pytest.mark.anyio
async def test_site_proposal_uses_choice_panel_before_custom_selector(tmp_path, monkeypatch):
    seen_context = {}

    class FakeSiteProposalSkill:
        def explain_propose_stream_from_context(self, context):
            seen_context.update(context)
            yield "- Positions 1 and 3 look exposed in the unpaired region.\n"
            yield "- Confidence is high for conservative edits there."

        def propose_from_context(self, context):
            seen_context.update(context)
            return {
                "proposed_sites": [1, 3],
                "reasoning": "Loop positions look tolerant.",
                "confidence": "high",
            }

    monkeypatch.setattr(
        "aptgent.tui.steps.site_proposal.SiteProposalSkill",
        FakeSiteProposalSkill,
    )

    app = make_app(tmp_path)
    state = app.engine.create_run("site_choice_case")
    state.current_step = Step.SITE_PROPOSAL
    state.input_payload["initial_sequence"] = "ACGTAC"
    state.secondary_structure = SecondaryStructure(
        sequence="ACGTAC",
        dot_bracket="......",
        mfe=-1.2,
    )
    app.persistence.save(state)

    async with app.run_test() as pilot:
        await pilot.pause()
        app.set_run_id("site_choice_case")
        app.push_screen("chat")
        await pilot.pause()
        await pilot.pause()

        assert type(app.screen).__name__ == "ChatScreen"
        assert seen_context["secondary_structure"]["dot_bracket"] == "......"
        assert seen_context["sequence"] == "ACGTAC"
        assert app.screen.query_one(ActionMenuPanel) is not None
        app.screen.query_one("#action-menu", OptionList).focus()

        await pilot.press("down", "enter")
        await pilot.pause()

        panel = app.screen.query_one(MutationSitePanel)
        assert panel is not None
        assert panel.query_one("#btn-confirm-sites", Button) is not None


@pytest.mark.anyio
async def test_chat_activity_bubble_is_last_status_message(tmp_path):
    app = make_app(tmp_path)
    state = app.engine.create_run("activity_case")
    app.persistence.save(state)

    async with app.run_test() as pilot:
        await pilot.pause()
        app.set_run_id("activity_case")
        app.push_screen("chat")
        await pilot.pause()

        screen = app.screen
        screen.show_activity("Testing activity")
        await pilot.pause()

        activity = screen.query_one(ActivityBubble)
        chat_log = screen.query_one("#chat-log")
        assert activity is not None
        assert chat_log.children[-1] is activity

        screen.add_system_message("A normal message")
        await pilot.pause()

        assert chat_log.children[-1] is activity


def test_activity_bubble_animates_text_and_icon_together():
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    bubble = ActivityBubble("Testing activity")
    seen = []

    def capture(renderable):
        seen.append(renderable)

    bubble.update = capture  # type: ignore[method-assign]
    bubble._update_render()
    bubble._frame_idx = 2
    bubble._update_render()
    bubble.finalize()

    assert seen[0] == "[#6b7280]✳ Testing activity[/]"
    assert seen[1] == "[bold #facc15]✳ Testing activity[/]"
    assert seen[2] == "[bold #facc15]•[/] Testing activity"


def test_thinking_bubble_toggles_expansion():
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    bubble = ThinkingBubble()
    bubble.append_text("First thought.")

    assert bubble.expanded is False

    bubble.toggle()
    assert bubble.expanded is True

    bubble.toggle()
    assert bubble.expanded is False


def test_thinking_bubble_collapsed_header_shows_token_count_and_arrow():
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    bubble = ThinkingBubble()
    seen = []

    def capture(renderable):
        seen.append(renderable)

    bubble.update = capture  # type: ignore[method-assign]
    bubble.append_text("Reasoning in progress.")

    latest = seen[-1]
    assert "Thinking" in latest
    assert "tokens" in latest
    assert "▼" in latest
    assert "Thought process hidden" not in latest


@pytest.mark.anyio
async def test_ctrl_o_toggles_latest_thinking_bubble(tmp_path):
    app = make_app(tmp_path)
    state = app.engine.create_run("thinking_toggle_case")
    app.persistence.save(state)

    async with app.run_test() as pilot:
        await pilot.pause()
        app.set_run_id("thinking_toggle_case")
        app.push_screen("chat")
        await pilot.pause()

        screen = app.screen
        bubble = screen.add_thinking_message()
        bubble.append_text("Thinking details")
        await pilot.pause()

        assert bubble.expanded is False
        await pilot.press("ctrl+o")
        await pilot.pause()
        assert bubble.expanded is True


@pytest.mark.anyio
async def test_final_report_palette_exposes_report_commands(tmp_path):
    app = make_app(tmp_path)
    state = app.engine.create_run("report_commands_case")
    state.current_step = Step.FINAL_REPORT
    app.persistence.save(state)

    async with app.run_test() as pilot:
        await pilot.pause()
        app.set_run_id("report_commands_case")
        app.push_screen("chat")
        await pilot.pause()
        await pilot.pause()

        chat_input = app.screen.query_one("#chat-input")
        chat_input.value = "/"
        await pilot.pause()

        command_list = app.screen.query_one("#command-list", OptionList)
        assert [command_list.get_option_at_index(i).id for i in range(len(command_list.options))] == [
            "/resume",
            "/quit",
            "/export",
            "/finish",
            "/theme",
        ]


@pytest.mark.anyio
async def test_theme_command_opens_picker_from_welcome(tmp_path):
    app = make_app(tmp_path)

    async with app.run_test() as pilot:
        await pilot.pause()
        chat_input = app.screen.query_one("#chat-input")
        chat_input.value = "/theme"
        chat_input.focus()

        await pilot.press("enter")
        await pilot.pause()

        assert isinstance(app.screen, ThemePickerScreen)


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
