"""Tests for docking skip path and _is_docking_enabled."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from aptgent.domain.enums import Step
from aptgent.tui.steps.docking_selection import (
    DockingSelectionHandler,
    _machine_profile,
    _top_k_bundle,
)


class _FakeScreen:
    def __init__(self, app):
        self.app = app
        self.messages: list[str] = []
        self.advanced_to: Step | None = None

    def add_system_message(self, msg, *args, **kwargs):
        self.messages.append(msg)

    def advance_to_step(self, step):
        self.advanced_to = step

    def set_input_enabled(self, enabled):
        pass

    def set_input_placeholder(self, text):
        pass

    def add_structured_widget(self, widget):
        pass


def _make_state(candidates=None):
    docking_rec = SimpleNamespace(
        phase="initial",
        recommended_top_k=5,
        machine_profile={"cpu_count": 4, "memory_gb": 8},
        recommended_exhaustiveness=8,
        display_markdown="",
        reason="",
        strategy="",
        accepted=False,
        receptor_path_note="",
        grid_center_note="",
    )
    return SimpleNamespace(
        run_id="test-run",
        current_step=Step.DOCKING_SELECTION,
        context=SimpleNamespace(
            docking_recommendation=docking_rec,
            tertiary_structure=SimpleNamespace(
                provider=None, receptor_source=None,
                receptor_status=None, job_id=None,
                result_path=None, error=None,
            ),
        ),
        candidates=candidates or [],
        docking_plan=None,
        docking_results=[],
        time_budget=4,
        target_molecule=None,
    )


def _make_app(state, *, docking_enabled=True):
    config: dict[str, Any] = {}
    if not docking_enabled:
        config["docking"] = {"enabled": False}
    app = SimpleNamespace(
        current_state=state,
        config=config,
        persistence=SimpleNamespace(
            run_dir=lambda rid: SimpleNamespace(),
        ),
        runtime=SimpleNamespace(
            llm_client=None,
            create_skill=lambda cls: cls(),
        ),
    )

    def save_state():
        pass

    app.save_state = save_state
    return app


def test_skip_advances_to_specificity_filter():
    state = _make_state()
    app = _make_app(state)
    screen = _FakeScreen(app)
    handler = DockingSelectionHandler(screen)
    handler._skip()
    assert screen.advanced_to == Step.SPECIFICITY_FILTER


def test_is_docking_enabled_true_by_default():
    state = _make_state()
    app = _make_app(state, docking_enabled=True)
    screen = _FakeScreen(app)
    handler = DockingSelectionHandler(screen)
    assert handler._is_docking_enabled() is True


def test_is_docking_enabled_false():
    state = _make_state()
    app = _make_app(state, docking_enabled=False)
    screen = _FakeScreen(app)
    handler = DockingSelectionHandler(screen)
    assert handler._is_docking_enabled() is False


def test_machine_profile_module_level():
    state = _make_state()
    profile = _machine_profile(state)
    assert profile["cpu_count"] == 4
    assert profile["memory_gb"] == 8


def test_top_k_bundle():
    from aptgent.domain.models import CandidateSequence
    candidates = [CandidateSequence(sequence=f"AA{i}", candidate_id=f"c{i}") for i in range(10)]
    state = _make_state(candidates=candidates)
    state.context.docking_recommendation.recommended_top_k = 3
    top_k, top_cands = _top_k_bundle(state)
    assert top_k == 3
    assert len(top_cands) == 3
