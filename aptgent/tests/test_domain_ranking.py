"""Tests for the cumulative ranking module."""
from __future__ import annotations

import numpy as np
import pytest

from aptgent.domain.ranking import ProbHistogramRanker, rank_sums_from_model_probs, select_top_y_by_affinity


class TestProbHistogramRanker:
    def test_single_model_single_candidate_rank_sum_is_1(self):
        ranker = ProbHistogramRanker(num_models=1)
        ranker.add([0.5])
        ranker.finalize()
        assert ranker.rank_sum([0.5]) == 1

    def test_two_candidates_dense_rank(self):
        ranker = ProbHistogramRanker(num_models=1)
        ranker.add([0.9])
        ranker.add([0.5])
        ranker.finalize()
        assert ranker.dense_rank([0.9]) == [1]
        assert ranker.dense_rank([0.5]) == [2]

    def test_tied_probabilities_get_same_min_rank(self):
        """Dense ranking.
        [0.9, 0.9, 0.8] → ranks [1, 1, 2]."""
        ranker = ProbHistogramRanker(num_models=1)
        ranker.add([0.9])
        ranker.add([0.9])
        ranker.add([0.8])
        ranker.finalize()
        assert ranker.dense_rank([0.9]) == [1]
        assert ranker.dense_rank([0.8]) == [2]

    def test_rank_sum_across_models(self):
        """3 models, 3 candidates. Verify rank_sum aggregation."""
        ranker = ProbHistogramRanker(num_models=3)
        # Candidate A: [0.9, 0.8, 0.7]
        ranker.add([0.9, 0.8, 0.7])
        # Candidate B: [0.5, 0.9, 0.8]
        ranker.add([0.5, 0.9, 0.8])
        # Candidate C: [0.7, 0.7, 0.9]
        ranker.add([0.7, 0.7, 0.9])
        ranker.finalize()

        # Model 0: A(0.9) > C(0.7) > B(0.5) → ranks 1, 3, 2
        # Wait, actually: A=0.9 is highest, so rank 1. C=0.7, one greater (A=0.9), rank 2. B=0.5, two greater, rank 3.
        # Model 1: B(0.9) > A(0.8) > C(0.7) → ranks 1, 2, 3
        # Model 2: C(0.9) > B(0.8) > A(0.7) → ranks 1, 2, 3
        assert ranker.dense_rank([0.9, 0.8, 0.7]) == [1, 2, 3]
        assert ranker.rank_sum([0.9, 0.8, 0.7]) == 6

        assert ranker.dense_rank([0.5, 0.9, 0.8]) == [3, 1, 2]
        assert ranker.rank_sum([0.5, 0.9, 0.8]) == 6

        assert ranker.dense_rank([0.7, 0.7, 0.9]) == [2, 3, 1]
        assert ranker.rank_sum([0.7, 0.7, 0.9]) == 6

    def test_rank_sum_matches_brute_force(self):
        """Verify ranker ranks match brute-force argsort-based dense ranks."""
        rng = np.random.RandomState(42)
        n_candidates = 500
        num_models = 9
        probs = rng.uniform(0.0, 1.0, (n_candidates, num_models))

        ranker = ProbHistogramRanker(num_models=num_models)
        for i in range(n_candidates):
            ranker.add(probs[i].tolist())
        ranker.finalize()

        # Brute-force dense ranks per model.
        for m in range(num_models):
            col = probs[:, m]
            order = np.argsort(-col)  # descending
            ranks = np.empty(n_candidates, dtype=int)
            current_rank = 1
            i = 0
            while i < n_candidates:
                # Find all ties at this level
                j = i
                while j < n_candidates and col[order[j]] == col[order[i]]:
                    j += 1
                for k in range(i, j):
                    ranks[order[k]] = current_rank
                current_rank += 1
                i = j

            for c in range(n_candidates):
                dense_rank = ranker.dense_rank(probs[c].tolist())[m]
                assert dense_rank == ranks[c], (
                    f"Model {m}, candidate {c}: dense_rank={dense_rank}, brute_force={ranks[c]}"
                )

    def test_rank_sum_ordering_differs_from_mean_prob(self):
        """Construct a case where mean-prob ranking differs from rank-sum ranking."""
        ranker = ProbHistogramRanker(num_models=3)
        # Candidate X: high average but inconsistent across models
        # Candidate Y: lower average but consistently near top
        #
        # Fill with many low-prob candidates first.
        for _ in range(100):
            ranker.add([0.1, 0.1, 0.1])
        # Candidate X: very high in one model, mediocre in two
        ranker.add([0.95, 0.6, 0.6])
        # Candidate Y: moderate across all models → lower rank_sum
        ranker.add([0.7, 0.7, 0.7])

        ranker.finalize()

        rs_x = ranker.rank_sum([0.95, 0.6, 0.6])
        rs_y = ranker.rank_sum([0.7, 0.7, 0.7])
        mean_x = (0.95 + 0.6 + 0.6) / 3
        mean_y = (0.7 + 0.7 + 0.7) / 3

        # X has higher mean probability (0.717 > 0.7) but Y has lower rank_sum
        assert mean_x > mean_y
        assert rs_y < rs_x

    def test_add_after_finalize_raises(self):
        ranker = ProbHistogramRanker(num_models=1)
        ranker.add([0.5])
        ranker.finalize()
        with pytest.raises(RuntimeError, match="Cannot add"):
            ranker.add([0.6])

    def test_rank_before_finalize_raises(self):
        ranker = ProbHistogramRanker(num_models=1)
        ranker.add([0.5])
        with pytest.raises(RuntimeError, match="finalize"):
            ranker.dense_rank([0.5])

    def test_wrong_number_of_probabilities_raises(self):
        ranker = ProbHistogramRanker(num_models=3)
        with pytest.raises(ValueError, match="Expected 3"):
            ranker.add([0.5, 0.6])

    def test_close_probabilities_are_not_quantized(self):
        """Full-precision probabilities that display the same still rank separately."""
        ranker = ProbHistogramRanker(num_models=1)
        values = [[0.90000049], [0.90000041], [0.90000039], [0.89999951]]
        for value in values:
            ranker.add(value)
        ranker.finalize()
        assert [round(value[0], 6) for value in values] == [0.9, 0.9, 0.9, 0.9]
        assert [ranker.rank_sum(value) for value in values] == [1, 2, 3, 4]

    def test_zero_probabilities(self):
        ranker = ProbHistogramRanker(num_models=2)
        ranker.add([0.0, 0.0])
        ranker.add([0.0, 0.5])
        ranker.finalize()
        assert ranker.rank_sum([0.0, 0.0]) == 3  # model0: 1 (tie), model1: 2
        assert ranker.rank_sum([0.0, 0.5]) == 2  # model0: 1 (tie), model1: 1

    def test_all_identical_probabilities(self):
        """All candidates with same probs get rank 1 everywhere."""
        ranker = ProbHistogramRanker(num_models=2)
        for _ in range(100):
            ranker.add([0.5, 0.5])
        ranker.finalize()
        assert ranker.rank_sum([0.5, 0.5]) == 2  # 1 + 1


class TestRankSumsFromModelProbs:
    """Tests for the in-memory rank_sums_from_model_probs helper."""

    def test_empty_input(self):
        assert rank_sums_from_model_probs([]) == []

    def test_single_candidate_single_model(self):
        assert rank_sums_from_model_probs([[0.5]]) == [1]

    def test_two_candidates_two_models(self):
        probs = [[0.9, 0.2], [0.3, 0.8]]
        result = rank_sums_from_model_probs(probs)
        # Model 0: 0.9 > 0.3 → ranks [1, 2]
        # Model 1: 0.8 > 0.2 → ranks [2, 1]
        assert result == [3, 3]

    def test_tied_probabilities_share_min_rank(self):
        probs = [[0.9], [0.9], [0.5]]
        result = rank_sums_from_model_probs(probs)
        # Both 0.9 tie at rank 1; 0.5 gets rank 2 (dense ranking, no gap)
        assert result == [1, 1, 2]

    def test_matches_brute_force_histogram(self):
        """rank_sums_from_model_probs should match ProbHistogramRanker results."""
        rng = np.random.RandomState(123)
        n_candidates = 200
        num_models = 9
        probs = rng.uniform(0.0, 1.0, (n_candidates, num_models))

        ranker = ProbHistogramRanker(num_models=num_models)
        for i in range(n_candidates):
            ranker.add(probs[i].tolist())
        ranker.finalize()

        expected = [ranker.rank_sum(probs[i].tolist()) for i in range(n_candidates)]
        actual = rank_sums_from_model_probs(probs.tolist())

        assert actual == expected

    def test_ordering_matches_intuition(self):
        # Consistently high → low rank_sum; spiky → higher rank_sum
        probs = [
            [0.95, 0.6, 0.6],   # spiky
            [0.7, 0.7, 0.7],    # consistent
            [0.1, 0.1, 0.1],    # low
        ]
        result = rank_sums_from_model_probs(probs)
        # Consistent candidate (idx 1) should beat spiky (idx 0)
        assert result[1] < result[0]
        # Low candidate should have highest rank_sum
        assert result[2] > result[0]
        assert result[2] > result[1]


class TestSelectTopYByAffinity:
    """Tests for the dense-rank top-y affinity selector."""

    def test_empty_results(self):
        assert select_top_y_by_affinity([], 5) == []

    def test_all_none_scores(self):
        results = [
            {"candidate_id": "a", "docking_score": None},
            {"candidate_id": "b", "docking_score": None},
        ]
        assert select_top_y_by_affinity(results, 5) == []

    def test_basic_top_3(self):
        results = [
            {"candidate_id": "a", "docking_score": -8.0},
            {"candidate_id": "b", "docking_score": -7.0},
            {"candidate_id": "c", "docking_score": -6.0},
            {"candidate_id": "d", "docking_score": -5.0},
            {"candidate_id": "e", "docking_score": -4.0},
        ]
        selected = select_top_y_by_affinity(results, 3)
        assert selected == ["a", "b", "c"]

    def test_ties_included(self):
        """3 tied at rank 1, 3 at rank 2, 3 at rank 3, 1 at rank 4, 1 at rank 5
        → top 5 dense rank includes all 11."""
        results = [
            {"candidate_id": f"a{i}", "docking_score": -8.0}
            for i in range(3)
        ] + [
            {"candidate_id": f"b{i}", "docking_score": -7.0}
            for i in range(3)
        ] + [
            {"candidate_id": f"c{i}", "docking_score": -6.0}
            for i in range(3)
        ] + [
            {"candidate_id": "d0", "docking_score": -5.0},
            {"candidate_id": "e0", "docking_score": -4.0},
        ]
        selected = select_top_y_by_affinity(results, 5)
        assert len(selected) == 11

    def test_ties_at_boundary_included(self):
        """If rank 2 has ties and top_y=2, all rank-2 candidates are included."""
        results = [
            {"candidate_id": "a", "docking_score": -9.0},
            {"candidate_id": "b", "docking_score": -8.0},
            {"candidate_id": "c", "docking_score": -8.0},
            {"candidate_id": "d", "docking_score": -7.0},
        ]
        selected = select_top_y_by_affinity(results, 2)
        assert "a" in selected
        assert "b" in selected
        assert "c" in selected
        assert "d" not in selected

    def test_top_y_larger_than_results(self):
        results = [
            {"candidate_id": "a", "docking_score": -8.0},
            {"candidate_id": "b", "docking_score": -7.0},
        ]
        selected = select_top_y_by_affinity(results, 10)
        assert len(selected) == 2

    def test_skips_none_scores(self):
        results = [
            {"candidate_id": "a", "docking_score": -8.0},
            {"candidate_id": "b", "docking_score": None},
            {"candidate_id": "c", "docking_score": -7.0},
        ]
        selected = select_top_y_by_affinity(results, 5)
        assert selected == ["a", "c"]

    def test_ascending_order_lower_is_better(self):
        results = [
            {"candidate_id": "worst", "docking_score": -1.0},
            {"candidate_id": "best", "docking_score": -10.0},
            {"candidate_id": "mid", "docking_score": -5.0},
        ]
        selected = select_top_y_by_affinity(results, 1)
        assert selected == ["best"]
