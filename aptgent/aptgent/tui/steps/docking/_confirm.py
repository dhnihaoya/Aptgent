"""Phase 4 mixin: read-only param confirmation + cover-aptamer recompute."""
from __future__ import annotations

from aptgent.domain.enums import Step
from aptgent.domain.models import GridBox
from aptgent.tui.steps.common import next_primary_step
from aptgent.tui.widgets.structured_input import DockingParamPanel

from ._helpers import _machine_profile


class _ConfirmMixin:
    """Phase 4: read-only plan confirmation and cover-aptamer recompute."""

    def _show_param_panel(self) -> None:
        state = self.screen.app.current_state
        recommendation = state.context.docking_recommendation
        plan = state.docking_plan
        if plan is None:
            self.screen.add_system_message(
                "Docking plan is not yet initialized; restarting selection.",
                "warning-text",
            )
            self._show_strategy_panel()
            return

        grid_boxes_view: dict[str, dict[str, list[float]]] = {}
        for cand_id, box in (plan.grid_boxes or {}).items():
            grid_boxes_view[cand_id] = {
                "center": list(box.center),
                "size": list(box.size),
            }

        recommendation.phase = "editing_form"
        self.screen.app.save_state()
        self.screen.add_structured_widget(
            DockingParamPanel(
                mode="llm" if recommendation.strategy == "llm" else "manual",
                machine_profile=plan.machine_profile or _machine_profile(state),
                time_budget=plan.time_budget or state.time_budget,
                recommended_exhaustiveness=plan.exhaustiveness,
                recommendation_reason=recommendation.reason,
                accepted_recommendation=recommendation.accepted,
                receptor_paths=dict(plan.receptor_paths or {}),
                grid_boxes=grid_boxes_view,
                grid_padding_angstrom=plan.grid_padding_angstrom,
                num_modes=plan.num_modes,
                energy_range=plan.energy_range,
                per_ligand_timeout_seconds=plan.per_ligand_timeout_seconds,
                seed=plan.seed,
                top_k=plan.recommended_top_k,
            )
        )
        self.screen.set_input_placeholder(
            "Review per-candidate receptors + boxes and submit when ready."
        )

    def _on_param_submitted(self, data: dict) -> None:
        state = self.screen.app.current_state
        plan = state.docking_plan
        if plan is None:
            self.screen.add_system_message(
                "Docking plan missing; restarting docking selection.",
                "warning-text",
            )
            self._show_strategy_panel()
            return

        recommendation = state.context.docking_recommendation
        recommendation.accepted = bool(data.get("accepted_recommendation"))
        recommendation.phase = "editing_form"
        self.screen.app.save_state()

        self.screen.add_system_message(
            f"Docking plan: {plan.recommended_top_k} candidates, "
            f"{len(plan.receptor_paths)} receptors, exhaustiveness={plan.exhaustiveness}."
        )
        ns = next_primary_step(Step.DOCKING_SELECTION)
        if ns:
            self.screen.advance_to_step(ns)

    def _cover_aptamer(self, padding_raw: str) -> None:
        state = self.screen.app.current_state
        plan = state.docking_plan
        if plan is None or not plan.receptor_paths:
            self.screen.add_system_message(
                "No per-candidate receptors loaded; cannot recompute boxes.",
                "warning-text",
            )
            return
        try:
            padding = float(padding_raw)
        except ValueError:
            padding = plan.grid_padding_angstrom
        prep = self._receptor_prep_adapter()
        grid_boxes: dict[str, GridBox] = {}
        for cand_id, path in plan.receptor_paths.items():
            try:
                box = prep.compute_box(path, padding=padding)
                grid_boxes[cand_id] = GridBox(center=list(box.center), size=list(box.size))
            except Exception as exc:
                self.screen.add_system_message(
                    f"Box recompute failed for {cand_id}: {exc}",
                    "error-text",
                )
                return
        plan.grid_boxes = grid_boxes
        plan.grid_padding_angstrom = padding
        self.screen.app.save_state()
        self.screen.add_system_message(
            f"Recomputed search boxes for {len(grid_boxes)} candidates (padding={padding} \u00c5)."
        )
        self._show_param_panel()
