"""Phase 1 mixin: strategy form (top_k, Vina knobs, LLM hint, NL parse)."""
from __future__ import annotations

from typing import Any

from aptgent.domain.models import DockingPlan
from aptgent.llm.skills import DockingPlannerSkill
from aptgent.tui.steps.common import (
    DEFAULT_ENERGY_RANGE,
    DEFAULT_GRID_PADDING_ANGSTROM,
    DEFAULT_NUM_MODES,
    compute_deterministic_docking_plan,
    format_docking_recommendation_markdown,
    run_llm_interaction,
    validate_docking_param_overrides,
    validate_docking_recommendation_result,
)
from aptgent.tui.steps.common.llm_ui import capture_streaming_result
from aptgent.tui.widgets.structured_input import DockingStrategyPanel
from aptgent.workflow.context import record_docking_recommendation_context

from ._helpers import (
    _machine_profile,
    _per_ligand_timeout_default_cached,
)


class _StrategyMixin:
    """Phase 1: strategy form with LLM hint and NL parse support."""

    def _show_strategy_panel(self) -> None:
        state = self.screen.app.current_state
        machine_profile = _machine_profile(state)
        candidate_count = len(state.candidates)
        plan = compute_deterministic_docking_plan(
            candidate_count=candidate_count,
            machine_profile=machine_profile,
            time_budget_hours=state.time_budget,
        )
        recommendation = state.context.docking_recommendation
        current_plan = state.docking_plan

        defaults = self._panel_defaults(
            recommendation=recommendation,
            current_plan=current_plan,
            computed_plan=plan,
            time_budget=state.time_budget,
        )

        recommendation.phase = "initial"
        recommendation.machine_profile = machine_profile
        recommendation.candidate_count = candidate_count
        self.screen.app.save_state()
        self.screen.add_structured_widget(
            DockingStrategyPanel(
                machine_profile=machine_profile,
                candidate_count=candidate_count,
                **defaults,
            )
        )
        self.screen.set_input_placeholder(
            "Describe docking parameter changes in natural language."
        )

    def _panel_defaults(
        self,
        *,
        recommendation: Any,
        current_plan: Any,
        computed_plan: dict,
        time_budget: int | None,
    ) -> dict[str, Any]:
        config_timeout = _per_ligand_timeout_default_cached()

        def _pick(plan_attr: str, rec_attr: str, fallback: Any) -> Any:
            if current_plan is not None:
                val = getattr(current_plan, plan_attr, None)
                if val is not None:
                    return val
            val = getattr(recommendation, rec_attr, None)
            if val is not None:
                return val
            return fallback

        top_k = _pick(
            "recommended_top_k",
            "recommended_top_k",
            computed_plan.get("recommended_top_k") or 100,
        )
        affinity_top_k = _pick(
            "affinity_top_k",
            "recommended_affinity_top_k",
            None,
        )
        exhaustiveness = _pick(
            "exhaustiveness",
            "recommended_exhaustiveness",
            computed_plan.get("recommended_exhaustiveness") or 8,
        )
        num_modes = _pick(
            "num_modes",
            "recommended_num_modes",
            DEFAULT_NUM_MODES,
        )
        energy_range = _pick(
            "energy_range",
            "recommended_energy_range",
            DEFAULT_ENERGY_RANGE,
        )
        padding = _pick(
            "grid_padding_angstrom",
            "recommended_grid_padding_angstrom",
            DEFAULT_GRID_PADDING_ANGSTROM,
        )
        per_ligand_timeout = _pick(
            "per_ligand_timeout_seconds",
            "recommended_per_ligand_timeout_seconds",
            None,
        )
        seed = _pick("seed", "recommended_seed", None)
        return {
            "default_top_k": int(top_k or 100),
            "default_affinity_top_k": (
                int(affinity_top_k) if affinity_top_k is not None else None
            ),
            "default_exhaustiveness": int(exhaustiveness or 8),
            "default_num_modes": int(num_modes or DEFAULT_NUM_MODES),
            "default_energy_range": float(energy_range or DEFAULT_ENERGY_RANGE),
            "default_grid_padding_angstrom": float(
                padding or DEFAULT_GRID_PADDING_ANGSTROM
            ),
            "default_per_ligand_timeout_seconds": (
                int(per_ligand_timeout)
                if per_ligand_timeout is not None
                else (
                    int(config_timeout)
                    if config_timeout is not None
                    else None
                )
            ),
            "default_time_budget_hours": (
                int(time_budget) if isinstance(time_budget, int) else None
            ),
            "default_seed": int(seed) if seed is not None else None,
        }

    def _on_strategy_submitted(self, data: dict) -> None:
        state = self.screen.app.current_state
        candidate_count = len(state.candidates)
        if candidate_count <= 0:
            self.screen.add_system_message(
                "No candidates available for docking.", "error-text"
            )
            return

        raw_overrides = {
            "top_k": data.get("top_k"),
            "affinity_top_k": data.get("affinity_top_k"),
            "exhaustiveness": data.get("exhaustiveness"),
            "num_modes": data.get("num_modes"),
            "energy_range": data.get("energy_range"),
            "grid_padding_angstrom": data.get("grid_padding_angstrom"),
            "per_ligand_timeout_seconds": data.get("per_ligand_timeout_seconds"),
            "time_budget_hours": data.get("time_budget_hours"),
            "seed": data.get("seed"),
        }
        applied, warnings, _ = validate_docking_param_overrides(
            raw_overrides,
            candidate_count=candidate_count,
        )
        for warning in warnings.values():
            self.screen.add_system_message(warning, "warning-text")

        top_k = applied.get("top_k") or 100
        if top_k > candidate_count:
            top_k = candidate_count

        affinity_top_k = applied.get("affinity_top_k")
        if affinity_top_k is not None:
            affinity_top_k = max(1, min(affinity_top_k, top_k))
        else:
            affinity_top_k = min(5, top_k)

        recommendation = state.context.docking_recommendation
        machine_profile = _machine_profile(state)
        plan = state.docking_plan or DockingPlan(
            machine_profile=machine_profile,
            recommended_top_k=top_k,
            exhaustiveness=applied.get("exhaustiveness", 8),
        )
        plan.machine_profile = plan.machine_profile or machine_profile
        plan.recommended_top_k = top_k
        plan.affinity_top_k = affinity_top_k
        if "exhaustiveness" in applied:
            plan.exhaustiveness = applied["exhaustiveness"]
        if "num_modes" in applied:
            plan.num_modes = applied["num_modes"]
        if "energy_range" in applied:
            plan.energy_range = applied["energy_range"]
        if "grid_padding_angstrom" in applied:
            plan.grid_padding_angstrom = applied["grid_padding_angstrom"]
        if "per_ligand_timeout_seconds" in applied:
            plan.per_ligand_timeout_seconds = applied["per_ligand_timeout_seconds"]
        else:
            plan.per_ligand_timeout_seconds = None
        if "seed" in applied:
            plan.seed = applied["seed"]
        else:
            plan.seed = None
        if "time_budget_hours" in applied:
            plan.time_budget = applied["time_budget_hours"]
        else:
            plan.time_budget = None
        state.docking_plan = plan

        state.time_budget = applied.get("time_budget_hours")
        recommendation.recommended_top_k = top_k
        recommendation.recommended_affinity_top_k = affinity_top_k
        recommendation.time_budget_hours = applied.get("time_budget_hours")
        recommendation.recommended_exhaustiveness = plan.exhaustiveness
        recommendation.recommended_num_modes = plan.num_modes
        recommendation.recommended_energy_range = plan.energy_range
        recommendation.recommended_grid_padding_angstrom = plan.grid_padding_angstrom
        recommendation.recommended_per_ligand_timeout_seconds = (
            plan.per_ligand_timeout_seconds
        )
        recommendation.recommended_seed = plan.seed
        recommendation.phase = "topk_selected"
        self.screen.app.save_state()
        self._show_filter_panel()

    def _current_form_seed(self) -> int | None:
        """Snapshot the seed from the active DockingStrategyPanel, if any."""
        widget = getattr(self.screen, "_active_structured_widget", None)
        if isinstance(widget, DockingStrategyPanel):
            return widget.live_params().get("seed")
        return None

    def _on_llm_hint(self) -> None:
        state = self.screen.app.current_state
        time_budget = state.time_budget
        plan = state.docking_plan
        top_k_default = (
            (plan.recommended_top_k if plan is not None else None)
            or state.context.docking_recommendation.recommended_top_k
            or 100
        )
        current_seed = self._current_form_seed()
        self.run_worker(
            lambda: self._llm_hint_worker(
                top_k_default, time_budget, current_seed=current_seed,
            ),
            activity="Preparing an LLM docking hint...",
        )

    def _llm_hint_worker(
        self,
        top_k_default: int,
        time_budget: int | None,
        *,
        user_guidance: str | None = None,
        current_seed: int | None = None,
    ) -> None:
        state = self.screen.app.current_state
        candidate_count = len(state.candidates)
        machine_profile = _machine_profile(state)
        target_smiles = state.target_molecule.smiles if state.target_molecule else None
        target_name = (
            state.target_molecule.resolved_name or state.target_molecule.input_text
            if state.target_molecule else None
        )
        plan = compute_deterministic_docking_plan(
            candidate_count=candidate_count,
            machine_profile=machine_profile,
            time_budget_hours=time_budget,
        )
        config_timeout = _per_ligand_timeout_default_cached()
        try:
            skill = self.screen.app.runtime.create_skill(DockingPlannerSkill)
            payload: dict[str, Any] = {
                "candidate_count": candidate_count,
                "machine_profile": machine_profile,
                "time_budget_hours": time_budget,
                "computed_top_k": plan["recommended_top_k"],
                "computed_time_budget_hours": plan["recommended_time_budget_hours"],
                "target_smiles": target_smiles,
                "target_name": target_name,
                "per_ligand_timeout_default_seconds": config_timeout,
            }
            if user_guidance:
                payload["user_guidance"] = user_guidance

            display_stream, get_captured = capture_streaming_result(
                lambda: skill.invoke_json_events(payload)
            )

            def structured_result() -> dict:
                captured = get_captured()
                if captured:
                    return validate_docking_recommendation_result(
                        captured,
                        candidate_count=candidate_count,
                        machine_profile=machine_profile,
                        time_budget_hours=time_budget,
                        target_smiles=target_smiles,
                        per_ligand_timeout_default=config_timeout,
                    )
                return validate_docking_recommendation_result(
                    skill.plan(**payload),
                    candidate_count=candidate_count,
                    machine_profile=machine_profile,
                    time_budget_hours=time_budget,
                    target_smiles=target_smiles,
                    per_ligand_timeout_default=config_timeout,
                )

            result = run_llm_interaction(
                self.screen,
                display_stream=display_stream,
                structured_call=structured_result,
            )
            top_k = result.get("recommended_top_k", top_k_default)
            exhaustiveness = result.get("recommended_exhaustiveness", 8)
            num_modes = result.get("recommended_num_modes", DEFAULT_NUM_MODES)
            energy_range = result.get("recommended_energy_range", DEFAULT_ENERGY_RANGE)
            grid_padding = result.get(
                "recommended_grid_padding_angstrom", DEFAULT_GRID_PADDING_ANGSTROM
            )
            per_ligand_timeout = result.get(
                "recommended_per_ligand_timeout_seconds",
                config_timeout,
            )
            seed = result.get("recommended_seed") or current_seed
            recommended_time = result.get("recommended_time_budget_hours")
            reason = result.get("reason", "")

            markdown = format_docking_recommendation_markdown(
                candidate_count=candidate_count,
                machine_profile=machine_profile,
                time_budget_hours=recommended_time,
                recommended_top_k=top_k,
                recommended_exhaustiveness=exhaustiveness,
                recommended_num_modes=num_modes,
                recommended_energy_range=energy_range,
                recommended_grid_padding_angstrom=grid_padding,
                recommended_per_ligand_timeout_seconds=per_ligand_timeout,
                recommended_seed=seed,
                receptor_path_note=result.get("receptor_path_note", ""),
                grid_center_note=result.get("grid_center_note", ""),
                reason=reason,
            )
            record_docking_recommendation_context(
                state,
                candidate_count=candidate_count,
                machine_profile=machine_profile,
                time_budget_hours=time_budget,
                recommended_time_budget_hours=recommended_time,
                recommended_top_k=top_k,
                recommended_exhaustiveness=exhaustiveness,
                recommended_num_modes=num_modes,
                recommended_energy_range=energy_range,
                recommended_per_ligand_timeout_seconds=per_ligand_timeout,
                recommended_grid_padding_angstrom=grid_padding,
                recommended_seed=seed,
                receptor_path_note=result.get("receptor_path_note", ""),
                grid_center_note=result.get("grid_center_note", ""),
                reason=reason,
                display_markdown=markdown,
                strategy="llm",
                phase="initial",
                accepted=False,
            )
            self.screen.app.save_state()
            overrides = {
                "top_k": top_k,
                "exhaustiveness": exhaustiveness,
                "num_modes": num_modes,
                "energy_range": energy_range,
                "grid_padding_angstrom": grid_padding,
                "per_ligand_timeout_seconds": per_ligand_timeout,
                "time_budget_hours": recommended_time,
                "seed": seed,
            }
            self._threadsafe(
                self._show_recommended_panel, overrides, markdown,
            )
        except Exception as exc:
            self._threadsafe(
                self.screen.add_system_message,
                f"LLM hint failed: {exc}",
                "error-text",
            )
        finally:
            self._enable_input()

    def _show_recommended_panel(
        self,
        overrides: dict[str, Any],
        markdown: str = "",
    ) -> None:
        """Replace the strategy panel with a confirm_only pre-filled panel."""
        if markdown:
            self.screen.add_system_message(markdown, "", True)
        state = self.screen.app.current_state
        machine_profile = _machine_profile(state)
        candidate_count = len(state.candidates)
        config_timeout = _per_ligand_timeout_default_cached()
        self.screen.add_structured_widget(
            DockingStrategyPanel(
                machine_profile=machine_profile,
                candidate_count=candidate_count,
                confirm_only=True,
                default_top_k=int(overrides.get("top_k") or 100),
                default_affinity_top_k=int(
                    overrides.get("affinity_top_k")
                    or min(5, overrides.get("top_k") or 100)
                ),
                default_exhaustiveness=int(
                    overrides.get("exhaustiveness") or 8
                ),
                default_num_modes=int(
                    overrides.get("num_modes") or DEFAULT_NUM_MODES
                ),
                default_energy_range=float(
                    overrides.get("energy_range") or DEFAULT_ENERGY_RANGE
                ),
                default_grid_padding_angstrom=float(
                    overrides.get("grid_padding_angstrom")
                    or DEFAULT_GRID_PADDING_ANGSTROM
                ),
                default_per_ligand_timeout_seconds=(
                    int(overrides["per_ligand_timeout_seconds"])
                    if overrides.get("per_ligand_timeout_seconds") is not None
                    else int(config_timeout) if config_timeout else None
                ),
                default_time_budget_hours=(
                    int(overrides["time_budget_hours"])
                    if overrides.get("time_budget_hours") is not None
                    else None
                ),
                default_seed=(
                    int(overrides["seed"])
                    if overrides.get("seed") is not None
                    else None
                ),
            )
        )
