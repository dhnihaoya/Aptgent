"""Main DockingSelectionHandler — composes all phase mixins."""
from __future__ import annotations

import threading
from typing import Any

from aptgent.adapters.receptor_prep import ReceptorPreparationAdapter
from aptgent.domain.enums import Step
from aptgent.tui.steps.base import StepHandler
from aptgent.tui.widgets.structured_input import DockingStrategyPanel
from aptgent.workflow.context import record_tertiary_structure_context

from ._confirm import _ConfirmMixin
from ._source import _SourceMixin
from ._strategy import _StrategyMixin
from ._structures import _StructuresMixin


class DockingSelectionHandler(
    StepHandler,
    _StrategyMixin,
    _SourceMixin,
    _StructuresMixin,
    _ConfirmMixin,
):
    """Multi-phase docking setup handler."""

    def __init__(self, screen: Any) -> None:
        super().__init__(screen)
        self._rnacomposer_cancel = threading.Event()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def enter(self) -> None:
        state = self.screen.app.current_state

        # If docking is disabled in config, skip directly to spatial_rank.
        if not self._is_docking_enabled():
            self._skip()
            return

        recommendation = state.context.docking_recommendation
        phase = recommendation.phase or "initial"

        self.screen.add_system_message(
            f"Step 6: Docking Selection\n"
            f"{len(state.candidates)} candidates available for docking."
        )

        if phase in ("editing_form", "structures_ready"):
            self._show_param_panel()
        elif phase == "awaiting_structures":
            self._show_manual_upload_panel()
        elif phase == "topk_selected":
            self._show_source_panel()
        else:
            self._show_strategy_panel()

        self.screen.set_input_enabled(True)

    # ------------------------------------------------------------------
    # Free-text / NL parse
    # ------------------------------------------------------------------

    def handle_user_input(self, text: str) -> None:
        cleaned = text.strip()
        if not cleaned:
            return

        state = self.screen.app.current_state
        phase = state.context.docking_recommendation.phase or "initial"
        if phase not in ("initial", "topk_selected"):
            self.screen.add_system_message(
                "Natural language overrides only apply to the strategy form. "
                "Use the panel actions or jump back to Phase 1.",
                "warning-text",
            )
            return

        if not isinstance(
            self.screen._active_structured_widget, DockingStrategyPanel
        ):
            self._show_strategy_panel()

        plan = state.docking_plan
        top_k_default = (
            (plan.recommended_top_k if plan is not None else None)
            or state.context.docking_recommendation.recommended_top_k
            or 100
        )

        self.run_worker(
            lambda: self._llm_hint_worker(
                top_k_default, state.time_budget, user_guidance=cleaned,
            ),
            activity="Preparing an LLM docking hint...",
        )

    # ------------------------------------------------------------------
    # Structured submissions
    # ------------------------------------------------------------------

    def handle_structured_input(self, data: dict) -> None:
        phase = data.get("phase")
        if phase in ("strategy_submitted", "topk_selected"):
            self._on_strategy_submitted(data)
            return
        if phase == "manual_upload":
            self._on_manual_upload_submitted(data)
            return
        if phase == "param_submitted":
            self._on_param_submitted(data)
            return
        # Backward-compat: legacy tests sent a single dict from the old
        # DockingParamPanel; treat that as a final param submit.
        self._on_param_submitted(data)

    # ------------------------------------------------------------------
    # Structured actions (buttons)
    # ------------------------------------------------------------------

    def handle_action(self, action: str) -> None:
        if action == "llm-hint" or action.startswith("llm-hint:"):
            self._on_llm_hint()
            return
        if action == "source:manual":
            self._on_source_selected("manual")
            return
        if action == "source:rnacomposer":
            self._on_source_selected("rnacomposer")
            return
        if action == "source:back":
            self._show_strategy_panel()
            return
        if action == "rnacomposer:cancel":
            self._rnacomposer_cancel.set()
            self.screen.add_system_message(
                "Cancelling RNAComposer job; returning to strategy panel.",
                "warning-text",
            )
            self._show_strategy_panel()
            self.screen.set_input_enabled(True)
            return
        if action.startswith("cover-aptamer:"):
            self._cover_aptamer(action.split(":", 1)[1])
            return

    # ------------------------------------------------------------------
    # Skip path
    # ------------------------------------------------------------------

    def _skip(self) -> None:
        state = self.screen.app.current_state
        state.docking_plan = None
        state.docking_results = []
        record_tertiary_structure_context(
            state,
            provider="rnacomposer",
            receptor_source="manual_input",
            receptor_status="skipped",
            result_path="",
            error="",
        )
        recommendation = state.context.docking_recommendation
        recommendation.display_markdown = ""
        recommendation.reason = ""
        recommendation.phase = "skipped"
        recommendation.strategy = "skipped"
        recommendation.accepted = False
        recommendation.recommended_top_k = 0
        recommendation.recommended_exhaustiveness = None
        recommendation.receptor_path_note = ""
        recommendation.grid_center_note = ""
        self.screen.app.save_state()
        self.screen.add_system_message("Docking skipped.")
        self.screen.advance_to_step(Step.SPECIFICITY_FILTER)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _receptor_prep_adapter(self) -> ReceptorPreparationAdapter:
        adapter = getattr(self.screen.app, "receptor_prep_adapter", None)
        if adapter is None:
            return ReceptorPreparationAdapter()
        return adapter

    def _is_docking_enabled(self) -> bool:
        config = getattr(self.screen.app, "config", {})
        docking_cfg = config.get("docking", {}) if isinstance(config, dict) else {}
        return docking_cfg.get("enabled", True)
