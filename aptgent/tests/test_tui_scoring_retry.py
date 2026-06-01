from __future__ import annotations

import pytest

from aptgent.domain.enums import Step
from aptgent.domain.models import PredictionResult, SecondaryStructure
from aptgent.tui.steps.scoring import ScoringHandler
from aptgent.tui.widgets.structured_input import ActionMenuPanel

from tui_helpers import anyio_backend, make_app


def test_primary_scoring_empty_llm_retry_rewinds_without_error_message(tmp_path):
    app = make_app(tmp_path)
    state = app.engine.create_run("empty_llm_retry")
    state.current_step = Step.PRIMARY_SCORING
    state.context.site_proposal.selection_source = "llm"
    state.context.site_proposal.needs_regeneration = True
    state.context.site_proposal.extra_context = {
        "site_selection_feedback": {"reason": "no_positive_candidates"}
    }
    app.persistence.save(state)
    app.set_run_id("empty_llm_retry")

    class FakeScreen:
        def __init__(self, app):
            self.app = app
            self.messages: list[tuple[str, str]] = []
            self.rewound_to: Step | None = None

        def add_system_message(self, text: str, extra_class: str = "", **_kwargs):
            self.messages.append((text, extra_class))

        def set_input_enabled(self, _enabled: bool):
            pass

        def rewind_to_step(self, step: Step, metadata=None):
            self.rewound_to = step
            self.app.engine.rewind_to(self.app.current_state, step, metadata=metadata)

    screen = FakeScreen(app)

    ScoringHandler(screen).enter()

    assert screen.rewound_to == Step.SITE_PROPOSAL
    assert app.current_state.context.site_proposal.needs_regeneration is True
    assert all(extra_class != "error-text" for _text, extra_class in screen.messages)
def test_primary_scoring_empty_llm_without_feedback_still_rewinds(tmp_path):
    app = make_app(tmp_path)
    state = app.engine.create_run("empty_llm_inferred")
    state.current_step = Step.PRIMARY_SCORING
    state.confirmed_mutation_sites = [1, 3]
    state.context.site_proposal.selection_source = "llm"
    state.context.site_proposal.selected_proposal_index = 1
    app.persistence.save(state)
    app.set_run_id("empty_llm_inferred")

    class FakeScreen:
        def __init__(self, app):
            self.app = app
            self.messages: list[tuple[str, str]] = []
            self.rewound_to: Step | None = None

        def add_system_message(self, text: str, extra_class: str = "", **_kwargs):
            self.messages.append((text, extra_class))

        def set_input_enabled(self, _enabled: bool):
            pass

        def rewind_to_step(self, step: Step, metadata=None):
            self.rewound_to = step
            self.app.engine.rewind_to(self.app.current_state, step, metadata=metadata)

    screen = FakeScreen(app)

    ScoringHandler(screen).enter()

    context = app.current_state.context.site_proposal
    assert screen.rewound_to == Step.SITE_PROPOSAL
    assert context.needs_regeneration is True
    assert context.preserve_proposal_indexes == [2]
    assert context.extra_context["site_selection_feedback"]["reason"] == "no_positive_candidates"
    assert all(extra_class != "error-text" for _text, extra_class in screen.messages)
def test_primary_scoring_empty_custom_sites_prompts_without_error_message(tmp_path):
    app = make_app(tmp_path)
    state = app.engine.create_run("empty_custom")
    state.current_step = Step.PRIMARY_SCORING
    state.context.site_proposal.selection_source = "custom"
    state.context.site_proposal.extra_context = {
        "site_selection_feedback": {"reason": "no_positive_candidates"}
    }
    app.persistence.save(state)
    app.set_run_id("empty_custom")

    class FakeScreen:
        def __init__(self, app):
            self.app = app
            self.messages: list[tuple[str, str]] = []
            self.input_enabled: list[bool] = []
            self.rewound_to: Step | None = None

        def add_system_message(self, text: str, extra_class: str = "", **_kwargs):
            self.messages.append((text, extra_class))

        def set_input_enabled(self, enabled: bool):
            self.input_enabled.append(enabled)

        def rewind_to_step(self, step: Step, metadata=None):
            self.rewound_to = step

    screen = FakeScreen(app)

    ScoringHandler(screen).enter()

    assert screen.rewound_to is None
    assert screen.input_enabled[-1] is True
    assert any(
        "no predicted binding mutations" in text.lower()
        for text, _class in screen.messages
    )
    assert all(extra_class != "error-text" for _text, extra_class in screen.messages)
def test_primary_scoring_empty_custom_without_feedback_prompts_without_error_message(tmp_path):
    app = make_app(tmp_path)
    state = app.engine.create_run("empty_custom_inferred")
    state.current_step = Step.PRIMARY_SCORING
    state.confirmed_mutation_sites = [1, 3]
    state.context.site_proposal.selection_source = "custom"
    app.persistence.save(state)
    app.set_run_id("empty_custom_inferred")

    class FakeScreen:
        def __init__(self, app):
            self.app = app
            self.messages: list[tuple[str, str]] = []
            self.input_enabled: list[bool] = []
            self.rewound_to: Step | None = None

        def add_system_message(self, text: str, extra_class: str = "", **_kwargs):
            self.messages.append((text, extra_class))

        def set_input_enabled(self, enabled: bool):
            self.input_enabled.append(enabled)

        def rewind_to_step(self, step: Step, metadata=None):
            self.rewound_to = step

    screen = FakeScreen(app)

    ScoringHandler(screen).enter()

    assert screen.rewound_to is None
    assert app.current_state.context.site_proposal.needs_regeneration is False
    assert screen.input_enabled[-1] is True
    assert any(
        "no predicted binding mutations" in text.lower()
        for text, _class in screen.messages
    )
    assert all(extra_class != "error-text" for _text, extra_class in screen.messages)
@pytest.mark.anyio
async def test_primary_scoring_back_reuses_site_proposal_choices(tmp_path, monkeypatch):
    calls = 0

    class FakeSiteProposalSkill:
        def __init__(self):
            nonlocal calls
            calls += 1

    monkeypatch.setattr(
        "aptgent.tui.steps.site_proposal.SiteProposalSkill",
        FakeSiteProposalSkill,
    )

    app = make_app(tmp_path)
    state = app.engine.create_run("primary_back_case")
    state.current_step = Step.PRIMARY_SCORING
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
            "reasoning": "Previously generated.",
            "confidence": "high",
        }
    ]
    state.context.site_proposal.proposed_sites = [1, 3]
    state.context.site_proposal.regeneration_reason = "Previous automatic retry reason."
    state.context.site_proposal.preserve_proposal_indexes = [0, 1]
    app.persistence.save(state)

    async with app.run_test() as pilot:
        await pilot.pause()
        app.set_run_id("primary_back_case")
        app.push_screen("chat")
        await pilot.pause()

        await pilot.click("#chat-input")
        await pilot.press("/", "b", "a", "c", "k", "enter")
        await pilot.pause()

        assert app.current_state.current_step == Step.SITE_PROPOSAL
        assert app.current_state.confirmed_mutation_sites == []
        assert app.current_state.context.site_proposal.needs_regeneration is False
        assert app.current_state.context.site_proposal.regeneration_reason is None
        assert app.current_state.context.site_proposal.preserve_proposal_indexes == []
        assert calls == 0
        assert app.screen.query_one(ActionMenuPanel) is not None
@pytest.mark.anyio
async def test_primary_scoring_back_from_empty_llm_state_triggers_regeneration(tmp_path):
    app = make_app(tmp_path)
    state = app.engine.create_run("primary_back_empty_llm")
    state.current_step = Step.PRIMARY_SCORING
    state.input_payload["initial_sequence"] = "ACGTAC"
    state.secondary_structure = SecondaryStructure(
        sequence="ACGTAC",
        dot_bracket="......",
        mfe=-1.2,
    )
    state.confirmed_mutation_sites = [1, 3]
    state.context.site_proposal.selection_source = "llm"
    state.context.site_proposal.selected_proposal_index = 0
    state.context.site_proposal.proposals = [
        {
            "label": "Conservative",
            "proposed_sites": [1, 3],
            "reasoning": "Previously generated.",
            "confidence": "high",
        },
        {
            "label": "Aggressive",
            "proposed_sites": [1, 3, 4],
            "reasoning": "Previously generated.",
            "confidence": "medium",
        },
        {
            "label": "Alternate",
            "proposed_sites": [2, 5],
            "reasoning": "Previously generated.",
            "confidence": "medium",
        },
    ]
    state.context.site_proposal.proposed_sites = [1, 3]
    app.persistence.save(state)

    async with app.run_test() as pilot:
        await pilot.pause()
        app.set_run_id("primary_back_empty_llm")
        app.push_screen("chat")
        await pilot.pause()

        await pilot.click("#chat-input")
        await pilot.press("/", "b", "a", "c", "k", "enter")
        await pilot.pause()

        context = app.current_state.context.site_proposal
        assert app.current_state.current_step == Step.SITE_PROPOSAL
        assert context.needs_regeneration is True
        assert context.preserve_proposal_indexes == [2]
        assert context.extra_context["site_selection_feedback"]["reason"] == (
            "no_positive_candidates"
        )


# ---------------------------------------------------------------------------
# Display tests: rank_sum / #rank format
# ---------------------------------------------------------------------------

class _FakeScreenForDisplay:
    """Minimal fake screen capturing add_system_message calls."""

    def __init__(self, app):
        self.app = app
        self.messages: list[str] = []
        self.advanced_to: Step | None = None

    def add_system_message(self, text: str, extra_class: str = "", **_kwargs):
        self.messages.append(text)

    def set_input_enabled(self, _enabled: bool):
        pass

    def advance_to_step(self, step: Step):
        self.advanced_to = step

    def show_activity(self, activity: str):
        pass

    def run_worker(self, fn, **kwargs):
        fn()

    def _threadsafe(self, fn, *args, **kwargs):
        fn(*args, **kwargs)


def _make_state_with_predictions(app, run_id, predictions):
    """Create a run with pre-populated predictions and matching candidates."""
    from aptgent.domain.models import CandidateSequence

    state = app.engine.create_run(run_id)
    state.current_step = Step.PRIMARY_SCORING
    state.predictions = predictions
    state.candidates = [
        CandidateSequence(candidate_id=p.candidate_id, sequence="ACGT", mutation_sites=[])
        for p in predictions
    ]
    state.target_molecule = None  # not needed for fast path
    app.persistence.save(state)
    app.set_run_id(run_id)
    return state


def test_show_existing_displays_rank_and_rank_sum(tmp_path):
    app = make_app(tmp_path)
    preds = [
        PredictionResult(
            candidate_id="cand_B",
            model_name="ensemble",
            target="X",
            score=0.8,
            label=1,
            probability=0.8,
            raw_outputs={"cumulative_rank": 2, "rank_sum": 14},
        ),
        PredictionResult(
            candidate_id="cand_A",
            model_name="ensemble",
            target="X",
            score=0.9,
            label=1,
            probability=0.9,
            raw_outputs={"cumulative_rank": 1, "rank_sum": 9},
        ),
    ]
    _make_state_with_predictions(app, "fast_display", preds)

    screen = _FakeScreenForDisplay(app)
    ScoringHandler(screen).enter()

    combined = "\n".join(screen.messages)
    assert "#1 cand_A" in combined
    assert "rank_sum=9" in combined
    assert "#2 cand_B" in combined
    assert "rank_sum=14" in combined


def test_show_existing_without_rank_sum_still_works(tmp_path):
    app = make_app(tmp_path)
    preds = [
        PredictionResult(
            candidate_id="cand_X",
            model_name="ensemble",
            target="X",
            score=0.7,
            label=0,
            probability=0.7,
            raw_outputs={"cumulative_rank": 1},
        ),
    ]
    _make_state_with_predictions(app, "fast_no_rs", preds)

    screen = _FakeScreenForDisplay(app)
    ScoringHandler(screen).enter()

    combined = "\n".join(screen.messages)
    assert "#1 cand_X" in combined
    assert "rank_sum=" not in combined
    assert "P=0.7000" in combined


def test_score_fallback_computes_rank_sum(tmp_path):
    app = make_app(tmp_path)
    state = app.engine.create_run("fallback_rs")
    state.current_step = Step.PRIMARY_SCORING
    from aptgent.domain.models import CandidateSequence, TargetMolecule

    state.candidates = [
        CandidateSequence(candidate_id="spiky", sequence="ACGT", mutation_sites=[0]),
        CandidateSequence(candidate_id="consistent", sequence="ACGA", mutation_sites=[0]),
    ]
    state.target_molecule = TargetMolecule(
        input_text="theophylline",
        resolved_name="theophylline",
        smiles="CN1C=NC2=C1C(=O)N(C(=O)N2C)C",
        resolution_status="resolved",
    )
    app.persistence.save(state)
    app.set_run_id("fallback_rs")

    # Mock predict_batch to return candidates with individual model probs.
    # spiky: high in model_a, low in model_b/c → rank_sum=5
    # consistent: moderate across all → rank_sum=4 (wins)
    mock_results = [
        PredictionResult(
            candidate_id="spiky",
            model_name="ensemble",
            target="CN1C=NC2=C1C(=O)N(C(=O)N2C)C",
            score=0.52,
            label=1,
            probability=0.52,
            raw_outputs={
                "individual": {
                    "model_a": {"label": 1, "probability": 0.95},
                    "model_b": {"label": 0, "probability": 0.3},
                    "model_c": {"label": 0, "probability": 0.3},
                }
            },
        ),
        PredictionResult(
            candidate_id="consistent",
            model_name="ensemble",
            target="CN1C=NC2=C1C(=O)N(C(=O)N2C)C",
            score=0.7,
            label=1,
            probability=0.7,
            raw_outputs={
                "individual": {
                    "model_a": {"label": 1, "probability": 0.7},
                    "model_b": {"label": 1, "probability": 0.7},
                    "model_c": {"label": 1, "probability": 0.7},
                }
            },
        ),
    ]
    app.prediction_adapter.predict_batch = lambda c, t: mock_results

    # call_from_thread requires a running Textual loop; patch to call directly.
    app.call_from_thread = lambda fn, *args, **kwargs: fn(*args, **kwargs)

    screen = _FakeScreenForDisplay(app)
    ScoringHandler(screen).enter()

    combined = "\n".join(screen.messages)
    # Should contain rank_sum in display
    assert "rank_sum=" in combined
    # "consistent" should rank higher (lower rank_sum) than "spiky"
    assert "#1 consistent" in combined
    assert "#2 spiky" in combined

    # Verify raw_outputs written
    updated_preds = app.current_state.predictions
    by_id = {p.candidate_id: p for p in updated_preds}
    assert "rank_sum" in by_id["consistent"].raw_outputs
    assert "rank_sum" in by_id["spiky"].raw_outputs
    assert "cumulative_rank" in by_id["consistent"].raw_outputs
    assert "cumulative_rank" in by_id["spiky"].raw_outputs
