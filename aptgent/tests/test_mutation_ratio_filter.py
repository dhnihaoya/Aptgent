"""Tests for mutation ratio filter logic and helpers."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from aptgent.domain.models import CandidateSequence, Mutation
from aptgent.tui.steps.docking._helpers import (
    _compute_mutation_ratio,
    _filtered_top_k_bundle,
    _top_k_bundle,
)


# ---------------------------------------------------------------------------
# _compute_mutation_ratio
# ---------------------------------------------------------------------------

def _cand(mutation_positions: list[int]) -> CandidateSequence:
    """Build a CandidateSequence with mutations at the given 0-based positions."""
    mutations = [
        Mutation(position=p, original="A", mutated="G")
        for p in mutation_positions
    ]
    return CandidateSequence(sequence="A" * 20, mutations=mutations)


def test_compute_mutation_ratio_all_mutated():
    cand = _cand([0, 3, 7])
    assert _compute_mutation_ratio(cand, [0, 3, 7]) == 1.0


def test_compute_mutation_ratio_none_mutated():
    cand = _cand([])  # no mutations
    assert _compute_mutation_ratio(cand, [0, 3, 7]) == 0.0


def test_compute_mutation_ratio_partial():
    cand = _cand([0, 7])  # 2 of 3 sites mutated
    assert _compute_mutation_ratio(cand, [0, 3, 7]) == pytest.approx(2 / 3)


def test_compute_mutation_ratio_empty_sites():
    cand = _cand([0, 3])
    # No confirmed sites → ratio is 1.0 by convention
    assert _compute_mutation_ratio(cand, []) == 1.0


def test_compute_mutation_ratio_subset_mutated():
    cand = _cand([2])
    assert _compute_mutation_ratio(cand, [2, 5, 10, 15]) == 0.25


# ---------------------------------------------------------------------------
# _filtered_top_k_bundle
# ---------------------------------------------------------------------------

def _state(
    candidates: list[CandidateSequence],
    *,
    confirmed_sites: list[int] | None = None,
    top_k: int = 100,
) -> SimpleNamespace:
    """Build a minimal state-like object for _filtered_top_k_bundle."""
    rec = SimpleNamespace(recommended_top_k=top_k)
    ctx = SimpleNamespace(docking_recommendation=rec)
    return SimpleNamespace(
        candidates=candidates,
        confirmed_mutation_sites=confirmed_sites or [],
        docking_plan=None,
        context=ctx,
    )


def test_filtered_top_k_bundle_respects_ratio():
    cands = [_cand([0, 3]), _cand([0]), _cand([]), _cand([0, 3, 7])]
    state = _state(cands, confirmed_sites=[0, 3, 7], top_k=4)
    # ratio >= 0.5 means 2/3 or 3/3 sites mutated (2/3 ≈ 0.667)
    count, filtered = _filtered_top_k_bundle(state, mutation_ratio=0.5)
    # _cand([0,3]) → 2/3 ≈ 0.667 >= 0.5 ✓; _cand([0,3,7]) → 1.0 >= 0.5 ✓
    assert count == 2
    assert filtered[0] is cands[0]  # _cand([0,3]) → 2/3
    assert filtered[1] is cands[3]  # _cand([0,3,7]) → 3/3


def test_filtered_top_k_bundle_no_ratio():
    cands = [_cand([0]), _cand([1])]
    state = _state(cands, confirmed_sites=[0, 1], top_k=2)
    count, filtered = _filtered_top_k_bundle(state, mutation_ratio=None)
    assert count == 2
    assert filtered == cands


def test_filtered_top_k_bundle_zero_ratio():
    """ratio=0.0 should pass through (is not None, but <= 0)."""
    cands = [_cand([]), _cand([0])]
    state = _state(cands, confirmed_sites=[0], top_k=2)
    count, filtered = _filtered_top_k_bundle(state, mutation_ratio=0.0)
    assert count == 2
    assert filtered == cands


def test_filtered_top_k_bundle_no_confirmed_sites():
    """No confirmed sites → passthrough regardless of ratio."""
    cands = [_cand([0]), _cand([1])]
    state = _state(cands, confirmed_sites=[], top_k=2)
    count, filtered = _filtered_top_k_bundle(state, mutation_ratio=1.0)
    assert count == 2
    assert filtered == cands


def test_filtered_top_k_bundle_filters_strict():
    cands = [_cand([0, 3, 7]), _cand([0, 3]), _cand([0])]
    state = _state(cands, confirmed_sites=[0, 3, 7], top_k=3)
    # Only full match (3/3) passes at ratio=1.0
    count, filtered = _filtered_top_k_bundle(state, mutation_ratio=1.0)
    assert count == 1
    assert filtered[0].mutations[0].position == 0
    assert len(filtered[0].mutations) == 3
