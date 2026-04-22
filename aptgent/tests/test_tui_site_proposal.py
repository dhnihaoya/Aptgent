from __future__ import annotations

import pytest

from aptgent.domain.enums import Step
from aptgent.domain.models import SecondaryStructure
from aptgent.tui.steps.site_proposal import SiteProposalHandler
from aptgent.tui.widgets.structured_input import ActionMenuPanel, MutationSitePanel
from textual.widgets import Button, OptionList

from tui_helpers import anyio_backend, make_app


def test_site_proposal_reuses_saved_choices_without_llm(tmp_path, monkeypatch):
    calls = 0

    class FakeSiteProposalSkill:
        def __init__(self):
            nonlocal calls
            calls += 1

    class FakeScreen:
        def __init__(self, app):
            self.app = app
            self.messages: list[str] = []
            self.widgets: list[object] = []
            self.placeholders: list[str] = []
            self.input_enabled: list[bool] = []

        def add_system_message(self, text: str, *_args, **_kwargs):
            self.messages.append(text)

        def add_structured_widget(self, widget):
            self.widgets.append(widget)

        def set_input_placeholder(self, text: str):
            self.placeholders.append(text)

        def set_input_enabled(self, enabled: bool):
            self.input_enabled.append(enabled)

    monkeypatch.setattr(
        "aptgent.tui.steps.site_proposal.SiteProposalSkill",
        FakeSiteProposalSkill,
    )

    app = make_app(tmp_path)
    state = app.engine.create_run("site_reuse_case")
    state.current_step = Step.SITE_PROPOSAL
    state.input_payload["initial_sequence"] = "ACGTAC"
    state.secondary_structure = SecondaryStructure(
        sequence="ACGTAC",
        dot_bracket="......",
        mfe=-1.2,
    )
    state.context.site_proposal.proposals = [
        {
            "label": "Saved plan",
            "proposed_sites": [1, 3],
            "reasoning": "Saved from a previous recommendation.",
            "confidence": "high",
        }
    ]
    state.context.site_proposal.proposed_sites = [1, 3]
    state.context.site_proposal.regeneration_reason = "No binding candidates were found."
    app.persistence.save(state)
    app.set_run_id("site_reuse_case")
    screen = FakeScreen(app)

    SiteProposalHandler(screen).enter()

    assert calls == 0
    assert any("No binding candidates were found" in msg for msg in screen.messages)
    assert any(isinstance(widget, ActionMenuPanel) for widget in screen.widgets)
    assert screen.input_enabled[-1] is True
def test_site_proposal_regeneration_replaces_only_third_plan(tmp_path, monkeypatch):
    captured_context = {}
    captured_display_stream = object()
    captured_display_events: list[dict] = []
    propose_from_context_called = False

    class FakeSiteProposalSkill:
        def propose_events_from_context(self, context):
            captured_context.update(context)
            yield {
                "type": "reasoning",
                "text": "Assessing scaffold-tolerant and suspected binding regions.",
            }
            yield {
                "type": "result",
                "value": {
                    "region_assessment": [
                        {
                            "label": "Loop edge",
                            "category": "safer_scaffold",
                            "positions": [4, 5],
                            "rationale": "Peripheral loop bases are plausible scaffold edits.",
                            "confidence": "medium",
                        }
                    ],
                    "proposals": [
                        {
                            "label": "Replacement 3",
                            "proposed_sites": [4, 5],
                            "reasoning": "Replaces the failed third direction.",
                            "confidence": "medium",
                        },
                    ],
                },
            }

        def propose_from_context(self, context):
            nonlocal propose_from_context_called
            propose_from_context_called = True
            raise AssertionError("site proposal should not make a second JSON call")

    def fake_run_llm_interaction(_screen, *, display_stream, structured_call, structured_client=None):
        nonlocal captured_display_stream
        captured_display_stream = display_stream
        assert display_stream is not None
        for event in display_stream():
            captured_display_events.append(event)
        return structured_call()

    class FakeApp:
        def __init__(self, state):
            self._state = state
            self.saved = False

        @property
        def current_state(self):
            return self._state

        def call_from_thread(self, func, *args):
            return func(*args)

        def save_state(self):
            self.saved = True

    class FakeScreen:
        def __init__(self, state):
            self.app = FakeApp(state)
            self.messages: list[str] = []
            self.widgets: list[object] = []

        def update_activity(self, _text: str):
            pass

        def add_system_message(self, text: str, *_args, **_kwargs):
            self.messages.append(text)

        def add_structured_widget(self, widget):
            self.widgets.append(widget)

        def set_input_placeholder(self, _text: str):
            pass

        def set_input_enabled(self, _enabled: bool):
            pass

    monkeypatch.setattr(
        "aptgent.tui.steps.site_proposal.SiteProposalSkill",
        FakeSiteProposalSkill,
    )
    monkeypatch.setattr(
        "aptgent.tui.steps.site_proposal.run_llm_interaction",
        fake_run_llm_interaction,
    )

    app = make_app(tmp_path)
    state = app.engine.create_run("site_replace_third_case")
    state.current_step = Step.SITE_PROPOSAL
    state.input_payload["initial_sequence"] = "ACGTAC"
    state.secondary_structure = SecondaryStructure(
        sequence="ACGTAC",
        dot_bracket="......",
        mfe=-1.2,
    )
    state.context.site_proposal.proposals = [
        {"label": "Keep 1", "proposed_sites": [1], "reasoning": "keep first"},
        {"label": "Keep 2", "proposed_sites": [1, 3], "reasoning": "keep second"},
        {"label": "Replace 3", "proposed_sites": [2, 4], "reasoning": "failed third"},
    ]
    state.context.site_proposal.needs_regeneration = True
    state.context.site_proposal.regeneration_reason = "No binding candidates were found."
    state.context.site_proposal.preserve_proposal_indexes = [0, 1]
    screen = FakeScreen(state)

    SiteProposalHandler(screen)._propose()

    proposals = state.context.site_proposal.proposals
    assert [proposal["label"] for proposal in proposals] == [
        "Keep 1",
        "Keep 2",
        "Replacement 3",
    ]
    assert state.context.site_proposal.needs_regeneration is False
    assert state.context.site_proposal.proposed_sites == [1]
    assert state.context.site_proposal.reasoning == "keep first"
    assert captured_display_stream is not None
    assert captured_display_events == [
        {
            "type": "reasoning",
            "text": "Assessing scaffold-tolerant and suspected binding regions.",
        }
    ]
    assert propose_from_context_called is False
    assert "Region assessment" in "\n".join(screen.messages)
    assert captured_context["extra_context"]["site_selection_feedback"]["message"] == (
        "No binding candidates were found."
    )
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
                        "label": "Conservative loop plan",
                        "proposed_sites": [1, 3],
                        "reasoning": "Loop positions look tolerant.",
                        "confidence": "high",
                    },
                    {
                        "label": "Aggressive loop scan",
                        "proposed_sites": [1, 3, 4],
                        "reasoning": "Adds nearby loop positions while keeping the conservative sites.",
                        "confidence": "medium",
                    },
                    {
                        "label": "Junction probe",
                        "proposed_sites": [2, 5],
                        "reasoning": "Tests a distinct exposed region.",
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
        panel = app.screen.query_one(ActionMenuPanel)
        assert panel is not None
        assert panel.has_class("expanded-menu")
        app.screen.query_one("#action-menu", OptionList).focus()

        await pilot.press("down", "down", "down", "enter")
        await pilot.pause()

        site_panel = app.screen.query_one(MutationSitePanel)
        assert site_panel is not None
        assert site_panel.query_one("#btn-confirm-sites", Button) is not None
@pytest.mark.anyio
async def test_site_proposal_can_confirm_second_recommended_plan(tmp_path, monkeypatch):
    class FakeSiteProposalSkill:
        def explain_propose_stream_from_context(self, context):
            yield "- Two possible mutation plans are available.\n"

        def propose_from_context(self, context):
            return {
                "proposals": [
                    {
                        "label": "Conservative loop plan",
                        "proposed_sites": [1, 3],
                        "reasoning": "Loop positions look tolerant.",
                        "confidence": "high",
                    },
                    {
                        "label": "Aggressive loop scan",
                        "proposed_sites": [1, 3, 4],
                        "reasoning": "Adds nearby loop positions while keeping the conservative sites.",
                        "confidence": "medium",
                    },
                    {
                        "label": "Junction probe",
                        "proposed_sites": [2, 5],
                        "reasoning": "Tests a distinct exposed region.",
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
        assert menu.get_option_at_index(2).id == "use-recommended-sites-2"
        assert menu.get_option_at_index(3).id == "custom-sites"
        menu.focus()

        await pilot.press("down", "enter")
        await pilot.pause()

        assert app.current_state.confirmed_mutation_sites == [1, 3, 4]
        assert app.current_state.context.site_proposal.confirmed_sites == [1, 3, 4]
@pytest.mark.anyio
async def test_site_proposal_can_confirm_llm_alternative_plan(tmp_path, monkeypatch):
    class FakeSiteProposalSkill:
        def explain_propose_stream_from_context(self, context):
            yield "- Three possible mutation plans are available.\n"

        def propose_from_context(self, context):
            return {
                "proposals": [
                    {
                        "label": "Conservative loop plan",
                        "proposed_sites": [1, 3],
                        "reasoning": "Loop positions look tolerant.",
                        "confidence": "high",
                    },
                    {
                        "label": "Aggressive loop scan",
                        "proposed_sites": [1, 3, 4],
                        "reasoning": "Adds nearby loop positions while keeping the conservative sites.",
                        "confidence": "medium",
                    },
                    {
                        "label": "Junction probe",
                        "proposed_sites": [2, 5],
                        "reasoning": "Tests a distinct exposed region.",
                        "confidence": "medium",
                    },
                ],
            }

    monkeypatch.setattr(
        "aptgent.tui.steps.site_proposal.SiteProposalSkill",
        FakeSiteProposalSkill,
    )

    app = make_app(tmp_path)
    state = app.engine.create_run("site_alternative_plan_case")
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
        app.set_run_id("site_alternative_plan_case")
        app.push_screen("chat")
        await pilot.pause()
        await pilot.pause()

        menu = app.screen.query_one("#action-menu", OptionList)
        menu.focus()

        await pilot.press("down", "down", "enter")
        await pilot.pause()

        assert app.current_state.confirmed_mutation_sites == [2, 5]
        assert app.current_state.context.site_proposal.confirmed_sites == [2, 5]
