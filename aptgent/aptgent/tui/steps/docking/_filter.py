"""Phase 1.5 mixin: mutation ratio filter between strategy and source."""
from __future__ import annotations

from typing import Any

from aptgent.tui.widgets.structured_input import MutationRatioPanel

from ._helpers import (
    _compute_mutation_ratio,
    _filtered_top_k_bundle,
    _top_k_bundle,
)


class _FilterMixin:
    """Phase 1.5: mutation ratio filter between strategy and source."""

    def _show_filter_panel(self) -> None:
        state = self.screen.app.current_state
        recommendation = state.context.docking_recommendation
        confirmed_sites = state.confirmed_mutation_sites or []

        # If no confirmed sites, filter is meaningless — skip to source.
        if not confirmed_sites:
            self._show_source_panel()
            return

        top_k, top_candidates = _top_k_bundle(state)

        # Pre-compute (candidate_id, ratio) for all top_k candidates.
        candidate_ratios: list[tuple[str, float]] = []
        for i, cand in enumerate(top_candidates):
            cid = cand.candidate_id or f"cand_{i}"
            ratio = _compute_mutation_ratio(cand, confirmed_sites)
            candidate_ratios.append((cid.replace(" ", "_"), ratio))

        # Resolve default ratio with explicit is not None checks
        # to avoid swallowing 0.0.
        default_ratio: float
        if recommendation.mutation_ratio is not None:
            default_ratio = recommendation.mutation_ratio
        elif state.context.intake.mutation_ratio is not None:
            default_ratio = state.context.intake.mutation_ratio
        else:
            default_ratio = 1.0

        # Set phase to filtering and persist.
        recommendation.phase = "filtering"
        self.screen.app.save_state()

        plan = state.docking_plan
        affinity_top_k = plan.affinity_top_k if plan is not None else 1

        self.screen.add_structured_widget(
            MutationRatioPanel(
                candidate_ratios=candidate_ratios,
                total_count=top_k,
                affinity_top_k=affinity_top_k,
                default_ratio=default_ratio,
            )
        )
        self.screen.set_input_placeholder(
            "Adjust the mutation ratio filter, or type docking parameter changes."
        )

    def _on_filter_submitted(self, data: dict) -> None:
        state = self.screen.app.current_state
        recommendation = state.context.docking_recommendation

        ratio = data["mutation_ratio"]
        recommendation.mutation_ratio = ratio

        # Compute actual filtered count.
        filtered_count = _filtered_top_k_bundle(
            state, mutation_ratio=ratio,
        )[0]

        # Clamp affinity_top_k if fewer candidates remain.
        plan = state.docking_plan
        if plan is not None and plan.affinity_top_k is not None:
            plan.affinity_top_k = min(plan.affinity_top_k, filtered_count)
            recommendation.recommended_affinity_top_k = plan.affinity_top_k

        self.screen.app.save_state()
        self._show_source_panel()

    def _on_filter_skipped(self) -> None:
        state = self.screen.app.current_state
        recommendation = state.context.docking_recommendation
        recommendation.mutation_ratio = None
        self.screen.app.save_state()
        self._show_source_panel()
