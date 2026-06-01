"""Phase 1 mixin: strategy form (top_k, Vina knobs, LLM hint, NL parse)."""
from __future__ import annotations

from typing import Any

from aptgent.domain.models import DockingPlan
from aptgent.llm.skills import DockingParamsParseSkill, DockingPlannerSkill
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
            "Describe docking parameter changes in natural language, or type "
            "'skip' to skip docking."
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
            computed_plan.get("recommended_top_k") or 5,
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
            "default_top_k": int(top_k or 5),
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

        top_k = applied.get("top_k") or 5
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
        self._show_source_panel()

    def _on_llm_hint(self) -> None:
        state = self.screen.app.current_state
        time_budget = state.time_budget
        plan = state.docking_plan
        top_k_default = (
            (plan.recommended_top_k if plan is not None else None)
            or state.context.docking_recommendation.recommended_top_k
            or 5
        )
        self.run_worker(
            lambda: self._llm_hint_worker(top_k_default, time_budget),
            activity="Preparing an LLM docking hint...",
        )

    def _llm_hint_worker(
        self,
        top_k_default: int,
        time_budget: int | None,
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
            result = run_llm_interaction(
                self.screen,
                display_stream=lambda: skill.explain_plan_stream(
                    candidate_count=candidate_count,
                    machine_profile=machine_profile,
                    time_budget_hours=time_budget,
                    computed_top_k=plan["recommended_top_k"],
                    computed_time_budget_hours=plan["recommended_time_budget_hours"],
                    target_smiles=target_smiles,
                    target_name=target_name,
                    per_ligand_timeout_default_seconds=config_timeout,
                ),
                structured_call=lambda: validate_docking_recommendation_result(
                    skill.plan(
                        candidate_count=candidate_count,
                        machine_profile=machine_profile,
                        time_budget_hours=time_budget,
                        computed_top_k=plan["recommended_top_k"],
                        computed_time_budget_hours=plan["recommended_time_budget_hours"],
                        target_smiles=target_smiles,
                        target_name=target_name,
                        per_ligand_timeout_default_seconds=config_timeout,
                    ),
                    candidate_count=candidate_count,
                    machine_profile=machine_profile,
                    time_budget_hours=time_budget,
                    target_smiles=target_smiles,
                    per_ligand_timeout_default=config_timeout,
                ),
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
            seed = result.get("recommended_seed")
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
            self._threadsafe(
                self.screen.add_system_message, markdown, "", True
            )
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
                self._apply_overrides_to_panel,
                overrides,
                "Filled the form with LLM-recommended parameters; "
                "press Continue to accept or edit fields first.",
            )
        except Exception as exc:
            self._threadsafe(
                self.screen.add_system_message,
                f"LLM hint failed: {exc}",
                "error-text",
            )
        finally:
            self._enable_input()

    def _nl_parse_worker(
        self, text: str, live_params: dict[str, Any] | None = None
    ) -> None:
        state = self.screen.app.current_state
        candidate_count = len(state.candidates)
        current_params: dict[str, Any] = live_params or {}
        try:
            skill = self.screen.app.runtime.create_skill(DockingParamsParseSkill)
            raw = skill.parse(
                text,
                current_params=current_params,
                candidate_count=candidate_count,
            )
        except Exception as exc:
            self._report_error(
                f"Could not parse natural language overrides: {exc}"
            )
            return

        applied, warnings, action = validate_docking_param_overrides(
            raw, candidate_count=candidate_count
        )

        if action == "skip":
            self._threadsafe(self._skip)
            return
        if action == "use_llm_hint":
            self._enable_input()
            self._threadsafe(self._on_llm_hint)
            return
        if action == "use_defaults":
            applied = self._default_overrides()

        for warning in warnings.values():
            self._threadsafe(
                self.screen.add_system_message, warning, "warning-text"
            )

        if not applied and action != "apply":
            self._threadsafe(
                self.screen.add_system_message,
                "I did not understand any parameter overrides in that message. "
                "Try something like 'top 8, exhaustiveness 32, seed 42' or 'skip'.",
                "warning-text",
            )
            self._enable_input()
            return

        summary_lines = ["Applied from your message:"] if applied else []
        for key, val in applied.items():
            summary_lines.append(f"  - {key} = {val}")
        summary = "\n".join(summary_lines) if summary_lines else ""

        self._threadsafe(
            self._apply_overrides_to_panel,
            applied,
            summary,
        )
        self._enable_input()

    def _default_overrides(self) -> dict[str, Any]:
        state = self.screen.app.current_state
        candidate_count = len(state.candidates)
        machine_profile = _machine_profile(state)
        plan = compute_deterministic_docking_plan(
            candidate_count=candidate_count,
            machine_profile=machine_profile,
            time_budget_hours=state.time_budget,
        )
        return {
            "top_k": plan["recommended_top_k"] or 5,
            "exhaustiveness": plan["recommended_exhaustiveness"] or 8,
            "num_modes": DEFAULT_NUM_MODES,
            "energy_range": DEFAULT_ENERGY_RANGE,
            "grid_padding_angstrom": DEFAULT_GRID_PADDING_ANGSTROM,
            "per_ligand_timeout_seconds": _per_ligand_timeout_default_cached(),
            "time_budget_hours": state.time_budget,
            "seed": None,
        }

    def _apply_overrides_to_panel(
        self,
        overrides: dict[str, Any],
        summary: str,
    ) -> None:
        widget = self.screen._active_structured_widget
        if isinstance(widget, DockingStrategyPanel):
            widget.apply_overrides(overrides)
        if summary:
            self.screen.add_system_message(summary)
