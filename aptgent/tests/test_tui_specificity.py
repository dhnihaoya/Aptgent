from __future__ import annotations

import pytest

from aptgent.domain.enums import Step
from aptgent.domain.models import CandidateSequence, TargetMolecule
from textual.css.query import NoMatches
from textual.widgets import Input, OptionList, SelectionList

from aptgent.tui.widgets.chat_widgets import ProgressBubble
from aptgent.tui.widgets.structured_input import (
    ActionMenuPanel,
    AnalogCheckboxPanel,
    AnalogCustomPanel,
)

from tui_helpers import anyio_backend, make_app


@pytest.mark.anyio
async def test_specificity_step_shows_recommendations_before_edit_input(tmp_path, monkeypatch):
    class FakeAnalogSuggestionSkill:
        calls = 0

        def suggest_events(self, target):
            type(self).calls += 1
            yield {
                "type": "reasoning",
                "text": "Checking close methylxanthine neighbors.",
            }
            yield {
                "type": "result",
                "value": {
                    "analogs": [
                        {"name": "theobromine", "reason": "Shares the xanthine core."},
                        {
                            "name": "paraxanthine",
                            "reason": "Probes methylation-specific binding.",
                        },
                    ],
                    "note": "Start with high-priority xanthine neighbors.",
                },
            }

        def explain_suggest_stream(self, target):
            raise AssertionError("specificity should not make a separate explanation call")

        def suggest(self, target):
            raise AssertionError("specificity should not make a second JSON call")

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
        assert FakeAnalogSuggestionSkill.calls == 1
        assert app.screen.query_one(ActionMenuPanel) is not None

        app.screen.query_one("#action-menu", OptionList).focus()
        await pilot.press("down", "enter")
        await pilot.pause()

        panel = app.screen.query_one(AnalogCheckboxPanel)
        assert panel is not None
        assert panel.selection_list is not None
        selected = list(panel.selection_list.selected)
        assert "theobromine" in selected
        assert "paraxanthine" in selected


@pytest.mark.anyio
async def test_specificity_custom_choice_enables_bottom_input(tmp_path, monkeypatch):
    """Reject and Customize now routes through the bottom input bar, not a panel."""

    class FakeAnalogSuggestionSkill:
        def suggest_events(self, target):
            yield {
                "type": "reasoning",
                "text": "Checking close methylxanthine neighbors.",
            }
            yield {
                "type": "result",
                "value": {
                    "analogs": [
                        {"name": "theobromine", "reason": "Shares the xanthine core."},
                    ]
                },
            }

        def explain_suggest_stream(self, target):
            raise AssertionError("specificity should not make a separate explanation call")

        def suggest(self, target):
            raise AssertionError("specificity should not make a second JSON call")

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

        with pytest.raises(NoMatches):
            app.screen.query_one(AnalogCustomPanel)

        input_bar = app.screen.query_one("#input-bar")
        assert not input_bar.has_class("-disabled")


@pytest.mark.anyio
async def test_specificity_accept_dispatches_detached_job(tmp_path, monkeypatch):
    """Accepting recommendations must hand off to the detached job runner.

    Mirrors ``EnumerationHandler`` so the progress UI streams through the
    same ``events.jsonl`` pipeline as candidate enumeration.
    """

    class FakeAnalogSuggestionSkill:
        def suggest_events(self, target):
            yield {
                "type": "result",
                "value": {
                    "analogs": [
                        {"name": "theobromine", "reason": "shares xanthine"},
                    ]
                },
            }

        def suggest(self, target):
            raise AssertionError("unused")

        def explain_suggest_stream(self, target):
            raise AssertionError("unused")

    monkeypatch.setattr(
        "aptgent.tui.steps.specificity.AnalogSuggestionSkill",
        FakeAnalogSuggestionSkill,
    )

    captured: dict[str, object] = {}

    def fake_attach_or_spawn_job(self, *, on_event, on_done, on_error, activity):
        captured["activity"] = activity
        captured["on_event"] = on_event
        captured["on_done"] = on_done
        captured["on_error"] = on_error
        captured["job_step"] = self.JOB_STEP

    monkeypatch.setattr(
        "aptgent.tui.steps.specificity.JobAttachMixin.attach_or_spawn_job",
        fake_attach_or_spawn_job,
    )

    app = make_app(tmp_path)
    state = app.engine.create_run("specificity_attach_case")
    state.current_step = Step.SPECIFICITY_FILTER
    state.target_molecule = TargetMolecule(
        input_text="caffeine",
        resolved_name="Caffeine",
        smiles="Cn1cnc2n(C)c(=O)n(C)c(=O)c12",
        resolution_status="resolved",
    )
    state.candidates = [
        CandidateSequence(sequence="ACGU", candidate_id="c1"),
        CandidateSequence(sequence="ACGA", candidate_id="c2"),
    ]
    app.persistence.save(state)

    async with app.run_test() as pilot:
        await pilot.pause()
        app.set_run_id("specificity_attach_case")
        app.push_screen("chat")
        await pilot.pause()
        await pilot.pause()

        app.screen.query_one("#action-menu", OptionList).focus()
        await pilot.press("enter")
        await pilot.pause()

        assert captured.get("job_step") == "specificity_filter"
        assert "specificity" in str(captured.get("activity", "")).lower()
        assert callable(captured.get("on_event"))
        assert callable(captured.get("on_done"))
        assert callable(captured.get("on_error"))
        # ProgressBubble must be the same widget used by enumeration's UI.
        progress_bubbles = list(app.screen.query(ProgressBubble))
        assert len(progress_bubbles) == 1


@pytest.mark.anyio
async def test_specificity_back_button_returns_to_choices(tmp_path, monkeypatch):
    """Back button on Partially Accept returns to the recommendation menu."""

    class FakeAnalogSuggestionSkill:
        def suggest_events(self, target):
            yield {
                "type": "result",
                "value": {
                    "analogs": [
                        {"name": "theobromine", "reason": "Shares xanthine core."},
                    ]
                },
            }

        def suggest(self, target):
            raise AssertionError("unused")

        def explain_suggest_stream(self, target):
            raise AssertionError("unused")

    monkeypatch.setattr(
        "aptgent.tui.steps.specificity.AnalogSuggestionSkill",
        FakeAnalogSuggestionSkill,
    )

    app = make_app(tmp_path)
    state = app.engine.create_run("specificity_back_case")
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
        app.set_run_id("specificity_back_case")
        app.push_screen("chat")
        await pilot.pause()
        await pilot.pause()

        app.screen.query_one("#action-menu", OptionList).focus()
        await pilot.press("down", "enter")
        await pilot.pause()

        checkbox_panel = app.screen.query_one(AnalogCheckboxPanel)
        assert checkbox_panel is not None

        back_btn = checkbox_panel.query_one("#btn-back-analogs")
        back_btn.press()
        await pilot.pause()

        menu_panel = app.screen.query_one(ActionMenuPanel)
        assert menu_panel is not None
        with pytest.raises(NoMatches):
            app.screen.query_one(AnalogCheckboxPanel)


@pytest.mark.anyio
async def test_specificity_confirmation_panel_renders_resolved(tmp_path):
    """AnalogCustomPanel with resolved_pairs renders without IndexError."""

    app = make_app(tmp_path)

    async with app.run_test() as pilot:
        await pilot.pause()
        app.set_run_id("confirmation_panel_case")
        app.push_screen("chat")
        await pilot.pause()

        panel = AnalogCustomPanel(
            target_name="caffeine",
            resolved_pairs=[("theobromine", True), ("xyz999", False)],
        )
        app.screen.add_structured_widget(panel)
        await pilot.pause()

        confirm_btn = panel.query_one("#btn-confirm-custom")
        assert confirm_btn is not None
        retry_btn = panel.query_one("#btn-retry-custom")
        assert retry_btn is not None
