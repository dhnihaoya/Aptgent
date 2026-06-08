"""Memory-bounded cumulative ranking via probability histograms.

Maintains per-model counts keyed by exact float probability values.
Dense rank = (number of distinct probability values strictly greater) + 1.

Memory scales with the number of distinct probability values per model,
not the number of candidates.  For tree-based ensemble models the number
of distinct outputs is bounded by the number of leaf nodes, typically
orders of magnitude smaller than the candidate count.
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np


class ProbHistogramRanker:
    """Maintains per-model probability counts and computes rank-sums.

    Usage::

        ranker = ProbHistogramRanker(num_models=9)
        for candidate in stream:
            ranker.add(candidate.rank_probabilities)
        ranker.finalize()
        rs = ranker.rank_sum(candidate.rank_probabilities)
    """

    def __init__(self, num_models: int) -> None:
        self._num_models = num_models
        self._counts: list[dict[float, int]] = [
            defaultdict(int) for _ in range(num_models)
        ]
        self._finalized = False
        # _distinct_greater[m][p] = number of distinct probability values
        # strictly greater than p in model m.
        self._distinct_greater: list[dict[float, int]] | None = None

    @property
    def num_models(self) -> int:
        return self._num_models

    def add(self, model_probs: list[float] | tuple[float, ...]) -> None:
        """Increment counts for one candidate's model probabilities."""
        if self._finalized:
            raise RuntimeError("Cannot add samples after finalize()")
        if len(model_probs) != self._num_models:
            raise ValueError(
                f"Expected {self._num_models} probabilities, got {len(model_probs)}"
            )
        for m, p in enumerate(model_probs):
            self._counts[m][p] += 1

    def finalize(self) -> None:
        """Build lookup tables for dense rank computation."""
        if self._finalized:
            return
        self._distinct_greater = []
        for m in range(self._num_models):
            sorted_vals = sorted(self._counts[m].keys(), reverse=True)
            dg: dict[float, int] = {}
            for i, v in enumerate(sorted_vals):
                dg[v] = i
            self._distinct_greater.append(dg)
        self._finalized = True

    def dense_rank(self, model_probs: list[float] | tuple[float, ...]) -> list[int]:
        """Return per-model dense ranks (1-based).

        Rank = (number of distinct probability values strictly greater) + 1.
        Ties get the same rank and subsequent ranks are consecutive:
        e.g. [0.9, 0.9, 0.8] → [1, 1, 2].
        """
        if not self._finalized:
            raise RuntimeError("Must call finalize() before querying ranks")
        if len(model_probs) != self._num_models:
            raise ValueError(
                f"Expected {self._num_models} probabilities, got {len(model_probs)}"
            )
        ranks = []
        for m, p in enumerate(model_probs):
            ranks.append(self._distinct_greater[m][p] + 1)
        return ranks

    def rank_sum(self, model_probs: list[float] | tuple[float, ...]) -> int:
        """Return the sum of per-model dense ranks (lower is better)."""
        return sum(self.dense_rank(model_probs))


def rank_sums_from_model_probs(per_candidate_probs: list[list[float]]) -> list[int]:
    """Compute rank_sum for each candidate from per-model probabilities.

    Each inner list holds one candidate's probabilities across models
    (all lists must be the same length).  Uses argsort-based dense
    ranking per model, then sums across models.

    Returns a list of rank_sums in the same order as the input candidates.
    """
    if not per_candidate_probs:
        return []

    num_candidates = len(per_candidate_probs)
    num_models = len(per_candidate_probs[0])

    probs = np.array(per_candidate_probs, dtype=np.float64)
    ranks = np.zeros_like(probs, dtype=np.int64)

    for m in range(num_models):
        col = probs[:, m]
        # argsort descending
        order = np.argsort(-col)
        current_rank = 1
        i = 0
        while i < num_candidates:
            j = i
            while j < num_candidates and col[order[j]] == col[order[i]]:
                j += 1
            for k in range(i, j):
                ranks[order[k], m] = current_rank
            current_rank += 1
            i = j

    return ranks.sum(axis=1).tolist()


def select_top_y_by_affinity(
    docking_results: list[dict],
    top_y: int,
) -> list[str]:
    """Select candidate ids whose docking_score dense rank ≤ *top_y*.

    *docking_results* items must have ``candidate_id`` (str) and
    ``docking_score`` (float | None).  Only completed results with a score
    are considered.  Lower docking_score = stronger affinity.  Dense
    ranking is used: equal scores share the same rank and the next distinct
    score gets rank + 1.  All candidates with rank ≤ top_y are kept
    (so ties may produce more than top_y ids).

    Returns a list of candidate_id strings (may be shorter than top_y if
    fewer valid results exist).
    """
    scored = [
        (r["candidate_id"], r["docking_score"])
        for r in docking_results
        if r.get("docking_score") is not None
    ]
    if not scored:
        return []

    scored.sort(key=lambda x: x[1])

    selected: list[str] = []
    rank = 0
    prev_score = None
    for cid, score in scored:
        if score != prev_score:
            rank += 1
            prev_score = score
        if rank > top_y:
            break
        selected.append(cid)

    return selected


def competition_ranks(values: list[float], reverse: bool = False) -> list[int]:
    """Standard competition ranking ("1224"). Ties share the smallest rank."""
    order = sorted(range(len(values)), key=lambda i: values[i], reverse=reverse)
    ranks = [0] * len(values)
    last_val: float | None = None
    last_rank = 0
    for pos, idx in enumerate(order):
        v = values[idx]
        if last_val is None or v != last_val:
            last_rank = pos + 1
            last_val = v
        ranks[idx] = last_rank
    return ranks


def dense_ranks(values: list[float], reverse: bool = False) -> list[int]:
    """Dense ranking ("1223"). Ties share a rank, no gaps follow."""
    order = sorted(range(len(values)), key=lambda i: values[i], reverse=reverse)
    ranks = [0] * len(values)
    last_val: float | None = None
    cur = 0
    for idx in order:
        v = values[idx]
        if last_val is None or v != last_val:
            cur += 1
            last_val = v
        ranks[idx] = cur
    return ranks
