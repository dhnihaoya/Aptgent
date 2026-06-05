from __future__ import annotations

import pytest

from aptgent.domain.enums import Step
from aptgent.domain.models import TargetMolecule
from aptgent.tui.commands import THEME_PRESETS
from aptgent.tui.app import AptgentApp
from aptgent.tui.screens.quit_confirm import QuitConfirmScreen
from aptgent.tui.screens.resume import _overview, _timestamp_label
from aptgent.tui.screens.theme_picker import ThemePickerScreen
from aptgent.tui.screens.welcome import WelcomeScreen
from aptgent.tui.widgets.chat_widgets import InputBar
from textual.css.query import NoMatches
from textual.widgets import OptionList, TextArea

from tui_helpers import anyio_backend, make_app


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
        assert app.theme == "clear-lanes"
        assert app.get_theme("clear-lanes").name == "clear-lanes"
def test_theme_presets_only_expose_refresh_options():
    assert [(preset.label, preset.theme_name) for preset in THEME_PRESETS] == [
        ("Clear Lanes", "clear-lanes"),
        ("Clean Minimal Light", "clean-minimal-light"),
        ("Warm Industrial", "warm-industrial"),
        ("QTY", "qty"),
        ("ZYX", "zyx"),
        ("QJX", "qjx"),
    ]
def test_welcome_hero_css_uses_theme_tokens():
    assert "#welcome-hero {\n        background: $panel;" in WelcomeScreen.CSS
    assert "#welcome-tagline {\n        color: $text;" in WelcomeScreen.CSS
    assert "#welcome-subtitle {\n        color: $text-muted;" in WelcomeScreen.CSS
    assert "#welcome-meta {" in WelcomeScreen.CSS
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
        welcome_bubbles = list(app.screen.query("#welcome-log SystemBubble"))
        assert any("**Step 1: Intake**" in bubble._text for bubble in welcome_bubbles)
        assert chat_input.placeholder == (
            "e.g. Design an aptamer for theophylline, sequence: GGGAAACCC... or provide a PDB ID"
        )
@pytest.mark.anyio
async def test_welcome_screen_has_refined_hero_elements(tmp_path):
    app = make_app(tmp_path)

    async with app.run_test() as pilot:
        await pilot.pause()

        meta = app.screen.query_one("#welcome-meta")
        assert meta is not None
        assert "Sequence" in str(meta.render())
        assert "/" in WelcomeScreen.LOGO
        assert "\\" in WelcomeScreen.LOGO
def test_welcome_logo_uses_ascii_safe_weave_core():
    lines = WelcomeScreen.LOGO.splitlines()
    assert len(lines) == 5
    assert all(len(line) == len(lines[0]) for line in lines)
    assert "╭" not in WelcomeScreen.LOGO
    assert "│" not in WelcomeScreen.LOGO
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
@pytest.mark.anyio
async def test_chat_input_wraps_and_grows_for_long_text(tmp_path):
    app = make_app(tmp_path)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        chat_input = app.screen.query_one("#chat-input", TextArea)
        input_bar = app.screen.query_one(InputBar)

        assert chat_input.soft_wrap is True
        assert input_bar.input_height == 3

        chat_input.load_text("Design an aptamer for caffeine. " * 12)
        await pilot.pause()

        assert 3 < input_bar.input_height <= 8
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
async def test_quit_confirm_button_exits_app(tmp_path):
    app = make_app(tmp_path)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+q")
        await pilot.pause()

        assert isinstance(app.screen, QuitConfirmScreen)

        await pilot.click("#quit-confirm")
        await pilot.pause()

        assert not app.is_running
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
        options = app.screen.query_one("#theme-option-list", OptionList)
        assert [options.get_option_at_index(index).id for index in range(len(options.options))] == [
            "clear-lanes",
            "clean-minimal-light",
            "warm-industrial",
            "qty",
            "zyx",
            "qjx",
        ]
