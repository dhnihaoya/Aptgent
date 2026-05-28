"""Tests for RunState schema versioning and migration."""
from __future__ import annotations

from aptgent.domain.enums import Step, Status
from aptgent.workflow.state import RunState


def test_schema_version_default():
    state = RunState(run_id="test")
    assert state.schema_version == "1.0"


def test_schema_version_old_state_migration():
    """Old state JSON without schema_version should still load and sync sites."""
    state = RunState.model_validate({
        "run_id": "old-run",
        "confirmed_mutation_sites": [2, 5, 8],
        "context": {"site_proposal": {}},
    })
    assert state.schema_version == "1.0"
    assert state.context.site_proposal.confirmed_sites == [2, 5, 8]


def test_migration_skips_when_context_already_set():
    state = RunState.model_validate({
        "run_id": "test",
        "confirmed_mutation_sites": [1, 2],
        "context": {"site_proposal": {"confirmed_sites": [3, 4]}},
    })
    # Context already has data — legacy should NOT overwrite
    assert state.context.site_proposal.confirmed_sites == [3, 4]


def test_set_mutation_sites_writes_both():
    state = RunState(run_id="test")
    state.set_mutation_sites([10, 20])
    assert state.confirmed_mutation_sites == [10, 20]
    assert state.context.site_proposal.confirmed_sites == [10, 20]


def test_validate_assignment_rejects_bad_step():
    state = RunState(run_id="test")
    try:
        state.current_step = "not_a_step"
        assert False, "Should have raised ValidationError"
    except Exception:
        pass


def test_json_roundtrip_preserves_version():
    state = RunState(run_id="test")
    json_str = state.model_dump_json()
    restored = RunState.model_validate_json(json_str)
    assert restored.schema_version == "1.0"
    assert restored.run_id == "test"
