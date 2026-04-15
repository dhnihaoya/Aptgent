from __future__ import annotations

import pytest

from aptgent.domain.enums import Step
from aptgent.domain.models import SecondaryStructure, TargetMolecule
from aptgent.tui.app import AptgentApp
from aptgent.tui.screens.resume import _overview, _timestamp_label
from aptgent.tui.widgets.chat_widgets import ActivityBubble
from aptgent.tui.widgets.structured_input import ActionMenuPanel, MutationSitePanel
from textual.css.query import NoMatches
from textual.widgets import OptionList


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
async def test_create_new_run_enters_chat_screen(tmp_path):
    app = make_app(tmp_path)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click("#btn-new-run")
        await pilot.pause()

        assert type(app.screen).__name__ == "ChatScreen"
        assert app.current_state.current_step == Step.INTAKE
        assert app.screen._handler.__class__.__name__ == "IntakeHandler"


@pytest.mark.anyio
async def test_welcome_screen_defaults_to_new_run_even_with_saved_runs(tmp_path):
    app = make_app(tmp_path)
    state = app.engine.create_run("resume_me")
    state.current_step = Step.PRIMARY_SCORING
    app.persistence.save(state)

    async with app.run_test() as pilot:
        await pilot.pause()

        new_run_input = app.screen.query_one("#new-run-input")
        assert app.screen.focused is new_run_input
        with pytest.raises(NoMatches):
            app.screen.query_one("#run-list")


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

    active = app.engine.create_run("active_run")
    active.current_step = Step.INTAKE
    app.persistence.save(active)

    resume_target = app.engine.create_run("resume_me")
    resume_target.current_step = Step.PRIMARY_SCORING
    resume_target.input_payload["initial_sequence"] = "ACGTACGT"
    resume_target.input_payload["target_molecule"] = "caffeine"
    app.persistence.save(resume_target)

    async with app.run_test() as pilot:
        await pilot.pause()
        app.set_run_id("active_run")
        app.push_screen("chat")
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
async def test_site_proposal_uses_choice_panel_before_custom_selector(tmp_path, monkeypatch):
    class FakeSiteProposalSkill:
        def propose(self, seq, struct):
            return {
                "proposed_sites": [1, 3],
                "reasoning": "Loop positions look tolerant.",
                "confidence": "high",
            }

    monkeypatch.setattr(
        "aptgent.tui.widgets.step_handlers.SiteProposalSkill",
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
        assert app.screen.query_one(ActionMenuPanel) is not None
        app.screen.query_one("#action-menu", OptionList).focus()

        await pilot.press("down", "enter")
        await pilot.pause()

        assert app.screen.query_one(MutationSitePanel) is not None


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
