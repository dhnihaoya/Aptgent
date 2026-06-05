"""Memory-bounded cumulative ranking via probability histograms.

Each ensemble model produces probabilities quantized to 6 decimal places
(`round(p, 6)`).  A 10^6-bucket histogram per model captures the full
distribution with zero loss, enabling exact dense ranks without
storing the full N×9 matrix in memory.

Memory: ``num_models × 10^6 × 8 B`` (~72 MB for 9 models), independent of
the number of candidates.
"""
from __future__ import annotations

import numpy as np


class ProbHistogramRanker:
    """Maintains per-model probability histograms and computes rank-sums.

    Usage::

        ranker = ProbHistogramRanker(num_models=9)
        for candidate in stream:
            ranker.add(candidate.model_probabilities)
        ranker.finalize()
        rs = ranker.rank_sum(candidate.model_probabilities)
    """

    def __init__(self, num_models: int, bins: int = 1_000_000) -> None:
        self._num_models = num_models
        self._bins = bins
        # One histogram per model (int64 to avoid overflow at ~10^9 candidates).
        self._histograms = np.zeros((num_models, bins), dtype=np.int64)
        self._finalized = False
        # greater_counts[m][b] = number of candidates with prob > b/bins in model m.
        # distinct_greater[m][b] = number of distinct probability values strictly > b/bins in model m.
        self._distinct_greater: np.ndarray | None = None

    @property
    def num_models(self) -> int:
        return self._num_models

    def add(self, model_probs: list[float] | tuple[float, ...]) -> None:
        """Increment histograms for one candidate's model probabilities."""
        if self._finalized:
            raise RuntimeError("Cannot add samples after finalize()")
        if len(model_probs) != self._num_models:
            raise ValueError(
                f"Expected {self._num_models} probabilities, got {len(model_probs)}"
            )
        for m, p in enumerate(model_probs):
            idx = min(int(round(p, 6) * self._bins), self._bins - 1)
            self._histograms[m, idx] += 1

    def finalize(self) -> None:
        """Compute suffix sums of distinct occupied bins for all models."""
        if self._finalized:
            return
        # Mark bins that have at least one candidate (distinct probability values).
        distinct_mask = (self._histograms > 0).astype(np.int64)
        # Reverse cumulative sum of distinct bins.
        self._distinct_greater = np.cumsum(distinct_mask[:, ::-1], axis=1)[:, ::-1]
        # Exclude the bin itself (strictly greater).
        self._distinct_greater -= distinct_mask
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
            idx = min(int(round(p, 6) * self._bins), self._bins - 1)
            distinct_greater = int(self._distinct_greater[m, idx])
            ranks.append(distinct_greater + 1)
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
