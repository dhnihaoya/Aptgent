"""Regression tests for the workflow engine transition DAG.

These tests pin down the active step order and guard against accidental
re-introduction of the removed ``DOCKING_PREP`` step.
"""

from __future__ import annotations

import json

import pytest

from aptgent.domain.enums import Step, Status
from aptgent.workflow.engine import TRANSITIONS, STEP_ORDER, WorkflowEngine
from aptgent.workflow.persistence import Persistence
from aptgent.workflow.state import RunState


def test_transitions_do_not_reference_removed_step():
    """``Step.DOCKING_PREP`` was removed; it must not appear anywhere."""
    assert not hasattr(Step, "DOCKING_PREP")
    for source, targets in TRANSITIONS.items():
        assert source is not None
        for dest in targets:
            assert dest.value != "docking_prep"


def test_transitions_cover_all_active_steps():
    for step in Step:
        if step == Step.FINAL_REPORT:
            assert TRANSITIONS[step] == []
            continue
        assert step in TRANSITIONS
        assert len(TRANSITIONS[step]) >= 1


def test_step_order_docking_before_specificity():
    """After primary_scoring comes docking_selection, not specificity_filter."""
    ps_idx = STEP_ORDER.index(Step.PRIMARY_SCORING)
    ds_idx = STEP_ORDER.index(Step.DOCKING_SELECTION)
    dr_idx = STEP_ORDER.index(Step.DOCKING_RUN)
    sf_idx = STEP_ORDER.index(Step.SPECIFICITY_FILTER)
    assert ds_idx == ps_idx + 1
    assert dr_idx == ds_idx + 1
    assert sf_idx == dr_idx + 1


def test_docking_selection_skip_transition():
    """DOCKING_SELECTION can skip to SPECIFICITY_FILTER (not SPATIAL_RANK)."""
    targets = TRANSITIONS[Step.DOCKING_SELECTION]
    assert Step.DOCKING_RUN in targets
    assert Step.SPECIFICITY_FILTER in targets


def test_workflow_engine_transition(tmp_path):
    persistence = Persistence(runs_dir=tmp_path)
    engine = WorkflowEngine(persistence)
    state = engine.create_run("run_abc")
    assert state.current_step == Step.INTAKE

    engine.transition_to(state, Step.SECONDARY_STRUCTURE)
    assert state.current_step == Step.SECONDARY_STRUCTURE
    assert state.status == Status.RUNNING

    with pytest.raises(ValueError):
        engine.transition_to(state, Step.FINAL_REPORT)


def test_workflow_engine_reload_preserves_step(tmp_path):
    persistence = Persistence(runs_dir=tmp_path)
    engine = WorkflowEngine(persistence)
    state = engine.create_run("persist_me")
    engine.transition_to(state, Step.SECONDARY_STRUCTURE)

    reloaded = engine.load_run("persist_me")
    assert reloaded is not None
    assert reloaded.current_step == Step.SECONDARY_STRUCTURE
    assert reloaded.run_id == "persist_me"


def test_workflow_engine_rewind_to_previous_step(tmp_path):
    persistence = Persistence(runs_dir=tmp_path)
    engine = WorkflowEngine(persistence)
    state = engine.create_run("rewind_me")
    state.current_step = Step.PRIMARY_SCORING
    persistence.save(state)

    engine.rewind_to(
        state,
        Step.SITE_PROPOSAL,
        metadata={"reason": "no_positive_candidates"},
    )

    reloaded = engine.load_run("rewind_me")
    assert reloaded is not None
    assert reloaded.current_step == Step.SITE_PROPOSAL
    log_path = persistence.run_dir("rewind_me") / "logs" / "workflow.jsonl"
    log_events = [json.loads(line)["event"] for line in log_path.read_text().splitlines()]
    assert "rewind" in log_events


def test_rewind_forward_raises(tmp_path):
    persistence = Persistence(runs_dir=tmp_path)
    engine = WorkflowEngine(persistence)
    state = engine.create_run("rewind_fwd")
    state.current_step = Step.INTAKE
    persistence.save(state)

    with pytest.raises(ValueError, match="Cannot rewind forward"):
        engine.rewind_to(state, Step.FINAL_REPORT)


def test_transition_from_completed_raises(tmp_path):
    persistence = Persistence(runs_dir=tmp_path)
    engine = WorkflowEngine(persistence)
    state = engine.create_run("done_run")
    state.status = Status.COMPLETED
    persistence.save(state)

    with pytest.raises(ValueError, match="terminal status"):
        engine.transition_to(state, Step.SECONDARY_STRUCTURE)


def test_transition_from_error_raises(tmp_path):
    persistence = Persistence(runs_dir=tmp_path)
    engine = WorkflowEngine(persistence)
    state = engine.create_run("err_run")
    state.status = Status.ERROR
    persistence.save(state)

    with pytest.raises(ValueError, match="terminal status"):
        engine.transition_to(state, Step.SECONDARY_STRUCTURE)
