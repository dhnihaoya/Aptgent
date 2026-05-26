from __future__ import annotations

from types import SimpleNamespace

import pytest

from aptgent.domain.enums import Step
from aptgent.tui.steps.enumeration import EnumerationHandler
from aptgent.workflow.engine import WorkflowEngine
from aptgent.workflow.persistence import Persistence


class FakeProgress:
    def __init__(self) -> None:
        self.updates: list[tuple[int, str]] = []
        self.finished: str | None = None

    def set_progress(self, processed: int, text: str) -> None:
        self.updates.append((processed, text))

    def finish(self, text: str) -> None:
        self.finished = text


class FakeScreen:
    def __init__(self) -> None:
        self.app = SimpleNamespace()
        self.messages: list[tuple[str, str]] = []

    def add_system_message(self, text: str, extra_class: str = "", *_args) -> None:
        self.messages.append((text, extra_class))


def test_enumeration_hit_events_update_progress_without_new_messages():
    screen = FakeScreen()
    handler = EnumerationHandler(screen)
    progress = FakeProgress()

    handler._on_job_event(
        {"type": "progress", "done": 128, "total": 256, "extra": {"binding": 1}},
        progress,
    )
    handler._on_job_event(
        {"type": "hit", "candidate_id": "hit_1", "probability": 0.8},
        progress,
    )
    handler._on_job_event(
        {"type": "hit", "candidate_id": "hit_2", "probability": 0.91},
        progress,
    )

    assert screen.messages == []
    assert progress.updates[-1] == (
        128,
        "Progress: 128/256 | Hits: 2 | Best P: 0.9100",
    )


@pytest.mark.parametrize(
    ("selected_index", "preserved_indexes", "expected_guidance"),
    [
        (0, [2], "larger mutation space"),
        (1, [2], "larger mutation space"),
        (2, [0, 1], "alternate"),
    ],
)
def test_enumeration_done_with_no_hits_after_llm_choice_sets_regeneration_feedback(
    tmp_path,
    selected_index,
    preserved_indexes,
    expected_guidance,
):
    persistence = Persistence(runs_dir=tmp_path)
    engine = WorkflowEngine(persistence)
    state = engine.create_run("zero_hits")
    state.current_step = Step.CANDIDATE_ENUMERATION
    state.confirmed_mutation_sites = [1, 3]
    state.context.site_proposal.selection_source = "llm"
    state.context.site_proposal.selected_proposal_index = selected_index
    state.context.site_proposal.proposals = [
        {"label": "Plan 1", "proposed_sites": [1], "reasoning": "first"},
        {"label": "Plan 2", "proposed_sites": [1, 3], "reasoning": "second"},
        {"label": "Plan 3", "proposed_sites": [2, 4], "reasoning": "third"},
    ]
    persistence.save(state)

    class FakeApp:
        def __init__(self):
            self.engine = engine
            self.persistence = persistence
            self._state = state
            self.saved = False

        @property
        def current_state(self):
            return self._state

        def save_state(self):
            self.saved = True
            self.persistence.save(self._state)

        def reload_current_state(self, run_id):
            self._state = self.engine.load_run(run_id)

    class RewindScreen(FakeScreen):
        def __init__(self):
            super().__init__()
            self.app = FakeApp()
            self.rewound_to: Step | None = None

        def rewind_to_step(self, step: Step, metadata=None) -> None:
            self.rewound_to = step
            self.app.engine.rewind_to(self.app.current_state, step, metadata=metadata)

    screen = RewindScreen()
    handler = EnumerationHandler(screen)
    progress = FakeProgress()

    handler._on_job_done(
        {"total": 16, "hits": 0, "kept": 0, "results_path": "/tmp/results.jsonl"},
        progress,
    )

    assert screen.rewound_to == Step.SITE_PROPOSAL
    context = screen.app.current_state.context.site_proposal
    assert context.needs_regeneration is True
    assert context.preserve_proposal_indexes == preserved_indexes
    feedback = context.extra_context["site_selection_feedback"]
    assert feedback["selected_proposal_index"] == selected_index
    assert expected_guidance in feedback["guidance"]
    assert "No binding candidates" in screen.messages[-1][0]
    assert screen.messages[-1][1] != "error-text"


def test_enumeration_done_with_no_hits_after_custom_sites_reuses_choices(tmp_path):
    persistence = Persistence(runs_dir=tmp_path)
    engine = WorkflowEngine(persistence)
    state = engine.create_run("zero_hits_custom")
    state.current_step = Step.CANDIDATE_ENUMERATION
    state.confirmed_mutation_sites = [1, 3]
    state.context.site_proposal.selection_source = "custom"
    state.context.site_proposal.proposals = [
        {"label": "Plan 1", "proposed_sites": [1], "reasoning": "first"},
        {"label": "Plan 2", "proposed_sites": [1, 3], "reasoning": "second"},
    ]
    persistence.save(state)

    class FakeApp:
        def __init__(self):
            self.engine = engine
            self.persistence = persistence
            self._state = state

        @property
        def current_state(self):
            return self._state

        def save_state(self):
            self.persistence.save(self._state)

        def reload_current_state(self, run_id):
            self._state = self.engine.load_run(run_id)

    class RewindScreen(FakeScreen):
        def __init__(self):
            super().__init__()
            self.app = FakeApp()
            self.rewound_to: Step | None = None

        def rewind_to_step(self, step: Step, metadata=None) -> None:
            self.rewound_to = step
            self.app.engine.rewind_to(self.app.current_state, step, metadata=metadata)

    screen = RewindScreen()
    handler = EnumerationHandler(screen)
    progress = FakeProgress()

    handler._on_job_done(
        {"total": 16, "hits": 0, "kept": 0, "results_path": "/tmp/results.jsonl"},
        progress,
    )

    assert screen.rewound_to == Step.SITE_PROPOSAL
    context = screen.app.current_state.context.site_proposal
    assert context.needs_regeneration is False
    assert context.preserve_proposal_indexes == []
    assert context.extra_context["site_selection_feedback"]["selection_source"] == "custom"
    assert screen.messages[-1][1] != "error-text"


def test_enumeration_done_when_cancelled_rewinds_to_site_proposal(tmp_path):
    persistence = Persistence(runs_dir=tmp_path)
    engine = WorkflowEngine(persistence)
    state = engine.create_run("cancelled_enum")
    state.current_step = Step.CANDIDATE_ENUMERATION
    persistence.save(state)

    class FakeApp:
        def __init__(self):
            self.engine = engine
            self.persistence = persistence
            self._state = state

        @property
        def current_state(self):
            return self._state

        def reload_current_state(self, run_id):
            self._state = self.engine.load_run(run_id)

    class CancelScreen(FakeScreen):
        def __init__(self):
            super().__init__()
            self.app = FakeApp()
            self.advanced_to: Step | None = None
            self.rewound_to: Step | None = None

        def rewind_to_step(self, step: Step, metadata=None) -> None:
            self.rewound_to = step

        def advance_to_step(self, step: Step) -> None:
            self.advanced_to = step

    screen = CancelScreen()
    handler = EnumerationHandler(screen)
    progress = FakeProgress()

    handler._on_job_done({"cancelled": True, "hits": 0}, progress)

    assert screen.advanced_to is None
    assert screen.rewound_to == Step.SITE_PROPOSAL
    assert any("cancelled" in text.lower() for text, _class in screen.messages)
