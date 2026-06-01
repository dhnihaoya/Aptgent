"""Memory-bounded cumulative ranking via probability histograms.

Each ensemble model produces probabilities quantized to 6 decimal places
(`round(p, 6)`).  A 10^6-bucket histogram per model captures the full
distribution with zero loss, enabling exact competition ranks without
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
        self._greater_counts: np.ndarray | None = None

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
        """Compute suffix sums (greater-than counts) for all models."""
        if self._finalized:
            return
        # Reverse cumulative sum: greater_counts[m][b] = sum of histogram[m][b+1:]
        # Equivalent to: cumulative sum of the reversed histogram, reversed back.
        self._greater_counts = np.cumsum(self._histograms[:, ::-1], axis=1)[:, ::-1]
        # Shift: greater_counts[m][b] should exclude the bucket itself.
        # After reversal cumsum, position b holds sum from b to end (inclusive).
        # We need strictly greater, so subtract self.
        self._greater_counts -= self._histograms
        self._finalized = True

    def competition_rank(self, model_probs: list[float] | tuple[float, ...]) -> list[int]:
        """Return per-model competition ranks (1-based, min/tie method).

        Rank = (number of candidates with strictly greater probability) + 1.
        Ties get the same rank (min convention): e.g. [0.9, 0.9, 0.8] → [1, 1, 3].
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
            greater = int(self._greater_counts[m, idx])
            ranks.append(greater + 1)
        return ranks

    def rank_sum(self, model_probs: list[float] | tuple[float, ...]) -> int:
        """Return the sum of per-model competition ranks (lower is better)."""
        return sum(self.competition_rank(model_probs))


def rank_sums_from_model_probs(per_candidate_probs: list[list[float]]) -> list[int]:
    """Compute rank_sum for each candidate from per-model probabilities.

    Each inner list holds one candidate's probabilities across models
    (all lists must be the same length).  Uses argsort-based competition
    ranking (min/tie convention) per model, then sums across models.

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
            current_rank = j + 1
            i = j

    return ranks.sum(axis=1).tolist()
