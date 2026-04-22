from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from aptgent.domain.enums import Step
from aptgent.domain.models import (
    CandidateSequence,
    PdbAnalysisResult,
    PdbChainCandidate,
    PdbLigandCandidate,
    SecondaryStructure,
    TargetMolecule,
)
from aptgent.tui.commands import THEME_PRESETS
from aptgent.tui.app import AptgentApp
from aptgent.tui.screens.quit_confirm import QuitConfirmScreen
from aptgent.tui.screens.resume import _overview, _timestamp_label
from aptgent.tui.screens.theme_picker import ThemePickerScreen
from aptgent.tui.screens.welcome import WelcomeScreen
from aptgent.tui.widgets.chat_widgets import (
    ActivityBubble,
    InputBar,
    SystemBubble,
    ThinkingBubble,
    UserBubble,
)
from aptgent.tui.widgets.structured_input import (
    ActionMenuPanel,
    DockingParamPanel,
    DockingStrategyPanel,
    MutationSitePanel,
    PdbSelectionPanel,
    SpecificityPanel,
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


class CountingRNAFoldAdapter(FakeRNAFoldAdapter):
    def __init__(self) -> None:
        self.calls: list[str] = []

    def fold(self, sequence: str) -> SecondaryStructure:
        self.calls.append(sequence)
        return super().fold(sequence)


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


class FakePdbAnalysisAdapter:
    def __init__(self):
        self.result = PdbAnalysisResult(
            pdb_id="1EHZ",
            title="Example aptamer structure",
            artifact_path="/tmp/1EHZ.pdb",
            nucleic_acid_chains=[
                PdbChainCandidate(chain_id="A", sequence="ACGU", residue_count=4, molecule_type="rna")
            ],
            ligands=[
                PdbLigandCandidate(
                    key="B:THP:101",
                    identifier="THP",
                    display_name="theophylline",
                    chain_id="B",
                    residue_number=101,
                    atom_count=12,
                )
            ],
        )

    def fetch(self, pdb_id, output_dir):
        return output_dir / f"{pdb_id}.pdb"

    def analyze(self, pdb_id, artifact_path):
        return self.result.model_copy(update={"pdb_id": pdb_id, "artifact_path": str(artifact_path)})

    def compare_sequence(self, user_sequence, pdb_sequence):
        if not user_sequence or not pdb_sequence:
            return "unknown"
        return "match" if user_sequence == pdb_sequence else "mismatch"

    def derive_secondary_structure(self, *, pdb_id, artifact_path, chain_id):
        return SecondaryStructure(
            sequence="ACGU",
            dot_bracket="(())",
            mfe=0.0,
            features={
                "source": "pdb_derived",
                "pdb_id": pdb_id,
                "chain_id": chain_id,
                "artifact_path": str(artifact_path),
            },
        )


def make_app(
    tmp_path,
    *,
    rna_fold_adapter=None,
    pdb_analysis_adapter=None,
    intake_skill_factory=None,
    pdb_review_skill_factory=None,
) -> AptgentApp:
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
        rna_fold_adapter=rna_fold_adapter or FakeRNAFoldAdapter(),
        prediction_adapter=FakePredictionAdapter(),
        vina_adapter=FakeVinaAdapter(),
        molecule_resolver=FakeResolver(),
        spatial_rank_adapter=FakeSpatialRankAdapter(),
        pdb_analysis_adapter=pdb_analysis_adapter or FakePdbAnalysisAdapter(),
        intake_skill_factory=intake_skill_factory,
        pdb_review_skill_factory=pdb_review_skill_factory,
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
        assert app.theme == "clear-lanes"
        assert app.get_theme("clear-lanes").name == "clear-lanes"


def test_theme_presets_only_expose_refresh_options():
    assert [(preset.label, preset.theme_name) for preset in THEME_PRESETS] == [
        ("Clear Lanes", "clear-lanes"),
        ("Clean Minimal Light", "clean-minimal-light"),
        ("Warm Industrial", "warm-industrial"),
    ]


def test_welcome_hero_css_uses_theme_tokens():
    assert "#welcome-hero {\n        background: $panel;" in WelcomeScreen.CSS
    assert "#welcome-tagline {\n        color: $text;" in WelcomeScreen.CSS
    assert "#welcome-subtitle {\n        color: $text-muted;" in WelcomeScreen.CSS
    assert "#welcome-meta {" in WelcomeScreen.CSS


def test_chat_bubble_default_css_enforces_lane_distinction():
    assert "margin: 0 4 1 0;" in SystemBubble.DEFAULT_CSS
    assert "width: 84%;" in SystemBubble.DEFAULT_CSS
    assert "border-left: wide $chat-system-accent;" in SystemBubble.DEFAULT_CSS
    assert "margin: 0 0 1 18;" in UserBubble.DEFAULT_CSS
    assert "width: 72%;" in UserBubble.DEFAULT_CSS
    assert "border-right: wide $chat-user-accent;" in UserBubble.DEFAULT_CSS
    assert "border-left: wide $chat-activity-accent;" in ActivityBubble.DEFAULT_CSS


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
                "proposals": [
                    {
                        "label": "Loop plan",
                        "proposed_sites": [1, 3],
                        "reasoning": "Loop positions look tolerant.",
                        "confidence": "high",
                    },
                    {
                        "label": "Compact plan",
                        "proposed_sites": [2, 4],
                        "reasoning": "Compact edits keep the search small.",
                        "confidence": "medium",
                    },
                ],
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

        await pilot.press("down", "down", "enter")
        await pilot.pause()

        panel = app.screen.query_one(MutationSitePanel)
        assert panel is not None
        assert panel.query_one("#btn-confirm-sites", Button) is not None


@pytest.mark.anyio
async def test_site_proposal_can_confirm_second_recommended_plan(tmp_path, monkeypatch):
    class FakeSiteProposalSkill:
        def explain_propose_stream_from_context(self, context):
            yield "- Two possible mutation plans are available.\n"

        def propose_from_context(self, context):
            return {
                "proposals": [
                    {
                        "label": "Loop plan",
                        "proposed_sites": [1, 3],
                        "reasoning": "Loop positions look tolerant.",
                        "confidence": "high",
                    },
                    {
                        "label": "Compact plan",
                        "proposed_sites": [2, 4],
                        "reasoning": "Compact edits keep the search small.",
                        "confidence": "medium",
                    },
                ],
            }

    monkeypatch.setattr(
        "aptgent.tui.steps.site_proposal.SiteProposalSkill",
        FakeSiteProposalSkill,
    )

    app = make_app(tmp_path)
    state = app.engine.create_run("site_second_plan_case")
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
        app.set_run_id("site_second_plan_case")
        app.push_screen("chat")
        await pilot.pause()
        await pilot.pause()

        menu = app.screen.query_one("#action-menu", OptionList)
        assert menu.get_option_at_index(0).id == "use-recommended-sites-0"
        assert menu.get_option_at_index(1).id == "use-recommended-sites-1"
        assert menu.get_option_at_index(2).id == "custom-sites"
        menu.focus()

        await pilot.press("down", "enter")
        await pilot.pause()

        assert app.current_state.confirmed_mutation_sites == [2, 4]
        assert app.current_state.context.site_proposal.confirmed_sites == [2, 4]


@pytest.mark.anyio
async def test_specificity_step_shows_recommendations_before_edit_input(tmp_path, monkeypatch):
    class FakeAnalogSuggestionSkill:
        def explain_suggest_stream(self, target):
            yield "- theobromine is a close methylxanthine analog.\n"
            yield "- paraxanthine can catch selectivity drift."

        def suggest(self, target):
            return {
                "analogs": [
                    {"name": "theobromine", "reason": "Shares the xanthine core."},
                    {"name": "paraxanthine", "reason": "Probes methylation-specific binding."},
                ],
                "note": "Start with high-priority xanthine neighbors.",
            }

    monkeypatch.setattr(
        "aptgent.tui.steps.specificity.AnalogSuggestionSkill",
        FakeAnalogSuggestionSkill,
    )

    app = make_app(tmp_path)
    state = app.engine.create_run("specificity_choice_case")
    state.current_step = Step.SPECIFICITY_FILTER
    state.target_molecule = TargetMolecule(
        input_text="caffeine",
        resolved_name="Caffeine",
        smiles="Cn1cnc2n(C)c(=O)n(C)c(=O)c12",
        resolution_status="resolved",
    )
    state.candidates = [CandidateSequence(sequence="ACGU", candidate_id="cand-1")]
    app.persistence.save(state)

    async with app.run_test() as pilot:
        await pilot.pause()
        app.set_run_id("specificity_choice_case")
        app.push_screen("chat")
        await pilot.pause()
        await pilot.pause()

        assert type(app.screen).__name__ == "ChatScreen"
        assert app.screen.query_one(ActionMenuPanel) is not None
        with pytest.raises(NoMatches):
            app.screen.query_one(SpecificityPanel)

        app.screen.query_one("#action-menu", OptionList).focus()
        await pilot.press("down", "enter")
        await pilot.pause()

        panel = app.screen.query_one(SpecificityPanel)
        assert panel is not None
        assert panel.query_one("#analog-input", Input).value == "theobromine, paraxanthine"


@pytest.mark.anyio
async def test_specificity_custom_choice_opens_blank_input(tmp_path, monkeypatch):
    class FakeAnalogSuggestionSkill:
        def explain_suggest_stream(self, target):
            yield "- theobromine is relevant.\n"

        def suggest(self, target):
            return {
                "analogs": [
                    {"name": "theobromine", "reason": "Shares the xanthine core."},
                ]
            }

    monkeypatch.setattr(
        "aptgent.tui.steps.specificity.AnalogSuggestionSkill",
        FakeAnalogSuggestionSkill,
    )

    app = make_app(tmp_path)
    state = app.engine.create_run("specificity_custom_case")
    state.current_step = Step.SPECIFICITY_FILTER
    state.target_molecule = TargetMolecule(
        input_text="caffeine",
        resolved_name="Caffeine",
        smiles="Cn1cnc2n(C)c(=O)n(C)c(=O)c12",
        resolution_status="resolved",
    )
    state.candidates = [CandidateSequence(sequence="ACGU", candidate_id="cand-1")]
    app.persistence.save(state)

    async with app.run_test() as pilot:
        await pilot.pause()
        app.set_run_id("specificity_custom_case")
        app.push_screen("chat")
        await pilot.pause()
        await pilot.pause()

        app.screen.query_one("#action-menu", OptionList).focus()
        await pilot.press("down", "down", "enter")
        await pilot.pause()

        panel = app.screen.query_one(SpecificityPanel)
        assert panel is not None
        assert panel.query_one("#analog-input", Input).value == ""


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


@pytest.mark.anyio
async def test_chat_screen_does_not_force_scroll_when_user_is_reading_history(tmp_path):
    app = make_app(tmp_path)
    state = app.engine.create_run("scroll_history_case")
    app.persistence.save(state)

    async with app.run_test() as pilot:
        await pilot.pause()
        app.set_run_id("scroll_history_case")
        app.push_screen("chat")
        await pilot.pause()

        screen = app.screen
        chat_log = screen.query_one("#chat-log")
        for index in range(40):
            screen.add_system_message(f"History block {index}\nLine A\nLine B")
        await pilot.pause()

        assert chat_log.max_scroll_y > 0

        chat_log.scroll_home(animate=False, immediate=True)
        await pilot.pause()

        scroll_before = chat_log.scroll_y
        screen.add_system_message("Newest update should not hijack the viewport.")
        await pilot.pause()

        assert chat_log.scroll_y == scroll_before
        assert not chat_log.is_vertical_scroll_end


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
    bubble._frame_idx = 3
    bubble._update_render()
    bubble.finalize()

    assert seen[0] == "[bold #a9bad1]run[/] [#5f6b7a]· Testing activity[/]"
    assert seen[1] == "[bold #a9bad1]run[/] [bold #f1c15b]✦ Testing activity[/]"
    assert seen[2] == "[bold #a9bad1]run[/] [bold #f1c15b]•[/] Testing activity"


@pytest.mark.anyio
async def test_chat_screen_tool_messages_use_distinct_bubble_class(tmp_path):
    app = make_app(tmp_path)
    state = app.engine.create_run("tool_message_case")
    app.persistence.save(state)

    async with app.run_test() as pilot:
        await pilot.pause()
        app.set_run_id("tool_message_case")
        app.push_screen("chat")
        await pilot.pause()

        bubble = app.screen.add_tool_message("**Running RNAfold**", label="tool")
        await pilot.pause()

        assert bubble.has_class("tool-bubble")
        assert isinstance(bubble, SystemBubble)


@pytest.mark.anyio
async def test_intake_retry_prompt_sets_retry_placeholder(tmp_path):
    app = make_app(tmp_path)
    state = app.engine.create_run("retry_prompt_case")
    state.input_payload["initial_sequence"] = "ACGU"
    state.context.intake.sequence = "ACGU"
    state.context.intake.phase = "awaiting_target_retry"
    state.context.intake.target_input = "bad target"
    state.context.intake.last_resolution_error = "Lookup failed."
    app.persistence.save(state)

    async with app.run_test() as pilot:
        await pilot.pause()
        app.set_run_id("retry_prompt_case")
        app.push_screen("chat")
        await pilot.pause()

        chat_input = app.screen.query_one("#chat-input", Input)
        bubbles = list(app.screen.query("#chat-log SystemBubble"))

        assert chat_input.placeholder == (
            "Enter a corrected molecule name or SMILES, or paste a full intake brief."
        )
        assert any("**Step 1: Intake Retry**" in bubble._text for bubble in bubbles)


@pytest.mark.anyio
async def test_intake_retry_accepts_full_brief_and_reruns_extraction(tmp_path):
    app = make_app(tmp_path)
    state = app.engine.create_run("retry_full_brief_case")
    state.input_payload["initial_sequence"] = "ACGU"
    state.context.intake.sequence = "ACGU"
    state.context.intake.phase = "awaiting_target_retry"
    state.context.intake.target_input = "bad target"
    state.context.intake.last_resolution_error = "Lookup failed."
    app.persistence.save(state)

    async with app.run_test() as pilot:
        await pilot.pause()
        app.set_run_id("retry_full_brief_case")
        app.push_screen("chat")
        await pilot.pause()

        handler = app.screen._handler
        called = {"extract": False}

        def fake_extract():
            called["extract"] = True

        handler._extract = fake_extract  # type: ignore[attr-defined]
        handler.run_worker = lambda work, activity: work()  # type: ignore[method-assign]

        handler.handle_user_input(
            "Design an aptamer for caffeine with sequence ACGU and low-cost screening."
        )

        assert called["extract"] is True
        assert app.current_state.context.intake.phase == "initial"
        assert app.current_state.input_payload["user_text"].startswith("Design an aptamer")


@pytest.mark.anyio
async def test_intake_retry_full_brief_heuristic_is_conservative_for_pdb_retry(tmp_path):
    app = make_app(tmp_path)
    state = app.engine.create_run("retry_heuristic_case")
    state.context.intake.phase = "awaiting_missing_target"
    state.context.intake.sequence = "ACGU"
    app.persistence.save(state)

    async with app.run_test() as pilot:
        await pilot.pause()
        app.set_run_id("retry_heuristic_case")
        app.push_screen("chat")
        await pilot.pause()

        handler = app.screen._handler
        assert handler._looks_like_full_intake("try pdb 1abc") is False
        assert handler._looks_like_full_intake("sequence ACGU target caffeine") is True


@pytest.mark.anyio
async def test_pdb_input_keeps_sequence_and_requests_missing_target(tmp_path):
    class FakeIntakeSkill:
        def extract(self, user_text):
            return {
                "pdb_id": "1EHZ",
                "input_mode": "pdb",
                "initial_sequence": None,
                "target_molecule": None,
            }

    class FakePdbReviewSkill:
        def review_summary(self, summary):
            return {"semantic_status": "aptamer_like", "note": "Looks like a nucleic-acid binder."}

    adapter = FakePdbAnalysisAdapter()
    adapter.result = adapter.result.model_copy(update={"ligands": []})
    app = make_app(
        tmp_path,
        pdb_analysis_adapter=adapter,
        intake_skill_factory=FakeIntakeSkill,
        pdb_review_skill_factory=FakePdbReviewSkill,
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        chat_input = app.screen.query_one("#chat-input", Input)
        chat_input.value = "1ehz"
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        await pilot.pause()

        assert app.current_state.current_step == Step.INTAKE
        assert app.current_state.context.intake.phase == "awaiting_missing_target"
        assert app.current_state.context.intake.sequence == "ACGU"
        assert app.current_state.context.pdb_intake.selected_chain_id == "A"


@pytest.mark.anyio
async def test_pdb_input_with_multiple_candidates_opens_selection_panel(tmp_path):
    class FakeIntakeSkill:
        def extract(self, user_text):
            return {
                "pdb_id": "1EHZ",
                "input_mode": "pdb",
                "initial_sequence": None,
                "target_molecule": None,
            }

    class FakePdbReviewSkill:
        def review_summary(self, summary):
            return {"semantic_status": "uncertain", "note": "Needs manual review."}

    adapter = FakePdbAnalysisAdapter()
    adapter.result = adapter.result.model_copy(
        update={
            "nucleic_acid_chains": [
                PdbChainCandidate(chain_id="A", sequence="ACGU", residue_count=4, molecule_type="rna"),
                PdbChainCandidate(chain_id="B", sequence="UGCA", residue_count=4, molecule_type="rna"),
            ],
            "ligands": [
                PdbLigandCandidate(
                    key="X:THP:101",
                    identifier="THP",
                    display_name="theophylline",
                    chain_id="X",
                    residue_number=101,
                    atom_count=12,
                ),
                PdbLigandCandidate(
                    key="Y:CAF:102",
                    identifier="CAF",
                    display_name="caffeine",
                    chain_id="Y",
                    residue_number=102,
                    atom_count=13,
                ),
            ],
        }
    )
    app = make_app(
        tmp_path,
        pdb_analysis_adapter=adapter,
        intake_skill_factory=FakeIntakeSkill,
        pdb_review_skill_factory=FakePdbReviewSkill,
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        chat_input = app.screen.query_one("#chat-input", Input)
        chat_input.value = "pdb 1ehz"
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        await pilot.pause()

        assert app.current_state.context.intake.phase == "awaiting_pdb_selection"
        assert app.screen.query_one(PdbSelectionPanel) is not None


@pytest.mark.anyio
async def test_mixed_pdb_input_prefers_pdb_sequence_over_user_sequence(tmp_path):
    class FakeIntakeSkill:
        def extract(self, user_text):
            return {
                "pdb_id": "1EHZ",
                "input_mode": "mixed",
                "initial_sequence": "AAAA",
                "target_molecule": "caffeine",
                "mixed_input_detected": True,
            }

    class FakePdbReviewSkill:
        def review_summary(self, summary):
            return {"semantic_status": "aptamer_like", "note": "PDB import looks usable."}

    app = make_app(
        tmp_path,
        pdb_analysis_adapter=FakePdbAnalysisAdapter(),
        intake_skill_factory=FakeIntakeSkill,
        pdb_review_skill_factory=FakePdbReviewSkill,
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        chat_input = app.screen.query_one("#chat-input", Input)
        chat_input.value = "sequence AAAA, pdb 1ehz, target caffeine"
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        await pilot.pause()

        assert app.current_state.current_step in {
            Step.SECONDARY_STRUCTURE,
            Step.SITE_PROPOSAL,
        }
        assert app.current_state.context.intake.sequence == "ACGU"
        assert app.current_state.context.pdb_intake.sequence_match_status == "mismatch"


def test_pdb_selection_panel_ignores_confirm_when_no_chain_options():
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    panel = PdbSelectionPanel(chain_choices=[], ligand_choices=[])
    fake_menu = SimpleNamespace(option_count=0, highlighted=None)
    posted = []

    panel.query_one = lambda *_args, **_kwargs: fake_menu  # type: ignore[method-assign]
    panel.post_message = lambda message: posted.append(message)  # type: ignore[method-assign]

    panel.on_button_pressed(SimpleNamespace(button=SimpleNamespace(id="btn-confirm-pdb-selection")))

    assert posted == []


@pytest.mark.anyio
async def test_secondary_structure_hides_not_configured_lookup_note(tmp_path):
    app = make_app(tmp_path)
    state = app.engine.create_run("structure_lookup_noise")
    state.current_step = Step.SECONDARY_STRUCTURE
    state.input_payload["initial_sequence"] = "ACGUACGU"
    app.persistence.save(state)

    async with app.run_test() as pilot:
        await pilot.pause()
        app.set_run_id("structure_lookup_noise")
        app.push_screen("chat")
        await pilot.pause()
        await pilot.pause()
        await pilot.pause()

        bubble_texts = [
            bubble._text
            for bubble in app.screen.query(SystemBubble)
            if hasattr(bubble, "_text")
        ]
        assert not any("No structure lookup adapter is configured" in text for text in bubble_texts)
        assert app.current_state.context.secondary_structure.note == "Secondary structure generated from RNAfold."


@pytest.mark.anyio
async def test_secondary_structure_prefers_pdb_derived_result_when_pdb_context_exists(tmp_path):
    rnafold = CountingRNAFoldAdapter()
    app = make_app(
        tmp_path,
        rna_fold_adapter=rnafold,
        pdb_analysis_adapter=FakePdbAnalysisAdapter(),
    )
    state = app.engine.create_run("structure_from_pdb")
    state.current_step = Step.SECONDARY_STRUCTURE
    state.input_payload["initial_sequence"] = "ACGU"
    state.context.pdb_intake.pdb_id = "1EHZ"
    state.context.pdb_intake.artifact_path = str(tmp_path / "1EHZ.pdb")
    state.context.pdb_intake.selected_chain_id = "A"
    app.persistence.save(state)

    async with app.run_test() as pilot:
        await pilot.pause()
        app.set_run_id("structure_from_pdb")
        app.push_screen("chat")
        await pilot.pause()
        await pilot.pause()
        await pilot.pause()

        assert rnafold.calls == []
        assert app.current_state.secondary_structure is not None
        assert app.current_state.secondary_structure.dot_bracket == "(())"
        assert app.current_state.context.secondary_structure.source == "pdb"
        bubble_texts = [
            bubble._text
            for bubble in app.screen.query(SystemBubble)
            if hasattr(bubble, "_text")
        ]
        assert any("Using PDB-derived secondary structure." in text for text in bubble_texts)


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
    assert "(ctrl+o to expand)" in latest
    assert "✦" in latest or "•" in latest or "·" in latest
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
        options = app.screen.query_one("#theme-option-list", OptionList)
        assert [options.get_option_at_index(index).id for index in range(len(options.options))] == [
            "clear-lanes",
            "clean-minimal-light",
            "warm-industrial",
        ]


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
