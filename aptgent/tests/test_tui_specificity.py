from __future__ import annotations

import pytest

from aptgent.domain.enums import Step
from aptgent.domain.models import CandidateSequence, TargetMolecule
from aptgent.tui.widgets.structured_input import ActionMenuPanel, SpecificityPanel
from textual.css.query import NoMatches
from textual.widgets import Input, OptionList

from tui_helpers import anyio_backend, make_app


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
