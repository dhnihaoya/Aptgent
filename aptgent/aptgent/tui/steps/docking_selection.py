"""Docking selection step handler.

Implements the multi-phase docking setup:

1. **strategy_form** \u2013 single form with EVERY Vina knob the user can
   tune (top_k, exhaustiveness, num_modes, energy_range, grid padding,
   per-ligand timeout, optional time-budget hint, optional seed). Both the
   LLM hint button and free-text NL parsing call back into the panel via
   ``apply_overrides`` instead of jumping straight to submit.
2. **source_selection** \u2013 choose receptor source: manual upload vs.
   automated RNAComposer scraping.
3. **structure_preparation** \u2013 either prompt the user for a structures
   directory or stream RNAComposer progress; in both cases we end up with
   per-candidate PDBQT files and bounding boxes.
4. **param_confirmation** \u2013 READ-ONLY summary of the plan + "Cover whole
   aptamer" recompute action + Submit & Continue.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from aptgent.adapters.docking import HardwareProbeAdapter
from aptgent.adapters.receptor_prep import (
    ReceptorPreparationAdapter,
    export_top_k_sequences,
    scan_structure_directory,
)
from aptgent.bootstrap.config import load_config
from aptgent.domain.enums import Step
from aptgent.domain.models import DockingPlan, GridBox
from aptgent.llm.skills import DockingParamsParseSkill, DockingPlannerSkill
from aptgent.tui.steps.base import StepHandler
from aptgent.tui.steps.common import (
    DEFAULT_ENERGY_RANGE,
    DEFAULT_GRID_PADDING_ANGSTROM,
    DEFAULT_NUM_MODES,
    DEFAULT_PER_LIGAND_TIMEOUT_SECONDS,
    compute_deterministic_docking_plan,
    format_docking_recommendation_markdown,
    next_step,
    run_llm_interaction,
    validate_docking_param_overrides,
    validate_docking_recommendation_result,
)
from aptgent.tui.widgets.structured_input import (
    DockingManualUploadPanel,
    DockingParamPanel,
    DockingRNAComposerProgressPanel,
    DockingSourcePanel,
    DockingStrategyPanel,
)
from aptgent.workflow.context import (
    record_docking_recommendation_context,
    record_tertiary_structure_context,
)

_log = logging.getLogger(__name__)


def _candidate_id(cand: Any, index: int) -> str:
    return cand.candidate_id or f"cand_{index}"


def _top_k_bundle(state: Any) -> tuple[int, list[Any]]:
    plan = state.docking_plan
    top_k = (
        (plan.recommended_top_k if plan is not None else None)
        or state.context.docking_recommendation.recommended_top_k
        or 5
    )
    return top_k, list(state.candidates[:top_k])


def _machine_profile(state: Any) -> dict[str, Any]:
    recommendation = state.context.docking_recommendation
    profile = recommendation.machine_profile or HardwareProbeAdapter().probe()
    return dict(profile)


def _per_ligand_timeout_default() -> int:
    """Resolve the per-ligand timeout fallback from workflow.toml."""
    try:
        bundle = load_config()
        return int(
            bundle.workflow.get("docking", {}).get(
                "per_ligand_timeout_seconds",
                DEFAULT_PER_LIGAND_TIMEOUT_SECONDS,
            )
        )
    except Exception:
        _log.debug("Failed to resolve per-ligand timeout default", exc_info=True)
        return DEFAULT_PER_LIGAND_TIMEOUT_SECONDS


_CACHED_TIMEOUT: int | None = None


def _per_ligand_timeout_default_cached() -> int:
    global _CACHED_TIMEOUT
    if _CACHED_TIMEOUT is None:
        _CACHED_TIMEOUT = _per_ligand_timeout_default()
    return _CACHED_TIMEOUT


def _apply_docking_plan(
    state: Any,
    *,
    receptor_paths: dict[str, str],
    grid_boxes: dict[str, dict[str, list[float]]],
    source: str,
    top_k: int,
) -> None:
    recommendation = state.context.docking_recommendation
    plan = state.docking_plan or DockingPlan(
        machine_profile=_machine_profile(state),
        recommended_top_k=top_k,
        exhaustiveness=recommendation.recommended_exhaustiveness or 8,
    )
    plan.receptor_paths = receptor_paths
    plan.grid_boxes = {
        cid: GridBox(center=box["center"], size=box["size"])
        for cid, box in grid_boxes.items()
    }
    plan.receptor_source = source
    plan.recommended_top_k = top_k
    state.docking_plan = plan
    recommendation.phase = "structures_ready"


class DockingSelectionHandler(StepHandler):
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
            f"Step 7: Docking Selection\n"
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
        lowered = cleaned.lower()
        if lowered == "skip" or "skip docking" in lowered or lowered in {
            "\u8df3\u8fc7", "\u8df3\u8fc7 docking",
        }:
            self._skip()
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

        # Snapshot live form values on the UI thread before the worker starts,
        # so the NL parser sees what the user currently has in the form.
        widget = self.screen._active_structured_widget
        live_params: dict[str, Any] = (
            widget.live_params()
            if isinstance(widget, DockingStrategyPanel)
            else {}
        )

        self.run_worker(
            lambda: self._nl_parse_worker(cleaned, live_params),
            activity="Parsing your docking parameters...",
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
        if action == "strategy:skip":
            self._skip()
            return
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
    # Phase 1: strategy form
    # ------------------------------------------------------------------

    def _show_strategy_panel(self) -> None:
        state = self.screen.app.current_state
        machine_profile = self._machine_profile(state)
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

        recommendation = state.context.docking_recommendation
        machine_profile = self._machine_profile(state)
        plan = state.docking_plan or DockingPlan(
            machine_profile=machine_profile,
            recommended_top_k=top_k,
            exhaustiveness=applied.get("exhaustiveness", 8),
        )
        plan.machine_profile = plan.machine_profile or machine_profile
        plan.recommended_top_k = top_k
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

    # ------------------------------------------------------------------
    # LLM hint
    # ------------------------------------------------------------------

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
        machine_profile = self._machine_profile(state)
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
            self.screen.app.call_from_thread(
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
            self.screen.app.call_from_thread(
                self._apply_overrides_to_panel,
                overrides,
                "Filled the form with LLM-recommended parameters; "
                "press Continue to accept or edit fields first.",
            )
        except Exception as exc:
            self.screen.app.call_from_thread(
                self.screen.add_system_message,
                f"LLM hint failed: {exc}",
                "error-text",
            )
        finally:
            self.screen.app.call_from_thread(self.screen.set_input_enabled, True)

    # ------------------------------------------------------------------
    # NL parse worker
    # ------------------------------------------------------------------

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
            self.screen.app.call_from_thread(
                self.screen.add_system_message,
                f"Could not parse natural language overrides: {exc}",
                "error-text",
            )
            self.screen.app.call_from_thread(self.screen.set_input_enabled, True)
            return

        applied, warnings, action = validate_docking_param_overrides(
            raw, candidate_count=candidate_count
        )

        if action == "skip":
            self.screen.app.call_from_thread(self._skip)
            return
        if action == "use_llm_hint":
            self.screen.app.call_from_thread(self.screen.set_input_enabled, True)
            self.screen.app.call_from_thread(self._on_llm_hint)
            return
        if action == "use_defaults":
            applied = self._default_overrides()

        for warning in warnings.values():
            self.screen.app.call_from_thread(
                self.screen.add_system_message, warning, "warning-text"
            )

        if not applied and action != "apply":
            self.screen.app.call_from_thread(
                self.screen.add_system_message,
                "I did not understand any parameter overrides in that message. "
                "Try something like 'top 8, exhaustiveness 32, seed 42' or 'skip'.",
                "warning-text",
            )
            self.screen.app.call_from_thread(self.screen.set_input_enabled, True)
            return

        summary_lines = ["Applied from your message:"] if applied else []
        for key, val in applied.items():
            summary_lines.append(f"  - {key} = {val}")
        summary = "\n".join(summary_lines) if summary_lines else ""

        self.screen.app.call_from_thread(
            self._apply_overrides_to_panel,
            applied,
            summary,
        )
        self.screen.app.call_from_thread(self.screen.set_input_enabled, True)

    def _default_overrides(self) -> dict[str, Any]:
        state = self.screen.app.current_state
        candidate_count = len(state.candidates)
        machine_profile = self._machine_profile(state)
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

    # ------------------------------------------------------------------
    # Phase 2: source selection
    # ------------------------------------------------------------------

    def _show_source_panel(self) -> None:
        state = self.screen.app.current_state
        top_k, _ = _top_k_bundle(state)
        self.screen.add_structured_widget(DockingSourcePanel(top_k=top_k))
        self.screen.set_input_placeholder(
            "Choose how the per-candidate structures will be prepared."
        )

    def _on_source_selected(self, source: str) -> None:
        state = self.screen.app.current_state
        top_k, top_candidates = _top_k_bundle(state)
        recommendation = state.context.docking_recommendation

        export_dir = (
            self.screen.app.persistence.run_dir(state.run_id)
            / "docking" / "sequences"
        )
        structures_dir = (
            self.screen.app.persistence.run_dir(state.run_id)
            / "docking" / "structures"
        )

        seq_pairs = [
            (_candidate_id(cand, i), cand.sequence)
            for i, cand in enumerate(top_candidates)
        ]
        try:
            export_top_k_sequences(seq_pairs, export_dir)
        except OSError as exc:
            self.screen.add_system_message(
                f"Failed to export sequences: {exc}", "error-text"
            )
            return

        recommendation.sequences_export_dir = str(export_dir)
        recommendation.structures_dir = str(structures_dir)

        if not state.docking_plan:
            state.docking_plan = DockingPlan(
                machine_profile=recommendation.machine_profile,
                time_budget=state.time_budget,
                recommended_top_k=top_k,
                exhaustiveness=recommendation.recommended_exhaustiveness or 8,
            )
        else:
            state.docking_plan.recommended_top_k = top_k
            state.docking_plan.time_budget = state.time_budget

        state.docking_plan.receptor_source = source

        if source == "manual":
            recommendation.phase = "awaiting_structures"
            recommendation.strategy = "manual"
            self.screen.app.save_state()
            self.screen.add_system_message(
                f"Top {top_k} sequences exported to:\n  {export_dir}\n"
                "Predict each candidate's 3D structure (e.g. RNAComposer + ADT) "
                "and place the resulting files into a directory using the "
                "naming convention cand_<id>.pdb / cand_<id>.pdbqt.",
                markdown=False,
            )
            self._show_manual_upload_panel()
            return

        if source == "rnacomposer":
            recommendation.phase = "preparing"
            recommendation.strategy = "rnacomposer"
            structures_dir.mkdir(parents=True, exist_ok=True)
            self.screen.app.save_state()
            self._rnacomposer_cancel.clear()
            self.run_worker(
                lambda: self._rnacomposer_worker(
                    [
                        (_candidate_id(cand, i), cand.sequence)
                        for i, cand in enumerate(top_candidates)
                    ],
                    structures_dir,
                ),
                activity="Submitting candidates to RNAComposer...",
            )
            self.screen.add_structured_widget(
                DockingRNAComposerProgressPanel(
                    total=len(top_candidates),
                    completed=0,
                )
            )

    # ------------------------------------------------------------------
    # Phase 3a: manual upload
    # ------------------------------------------------------------------

    def _show_manual_upload_panel(self) -> None:
        state = self.screen.app.current_state
        recommendation = state.context.docking_recommendation
        top_k, top_candidates = _top_k_bundle(state)
        candidate_ids = [
            _candidate_id(cand, i)
            for i, cand in enumerate(top_candidates)
        ]
        export_dir = recommendation.sequences_export_dir or str(
            self.screen.app.persistence.run_dir(state.run_id)
            / "docking" / "sequences"
        )
        default_dir = recommendation.structures_dir or str(
            self.screen.app.persistence.run_dir(state.run_id)
            / "docking" / "structures"
        )
        self.screen.add_structured_widget(
            DockingManualUploadPanel(
                export_dir=export_dir,
                candidate_ids=candidate_ids,
                default_structures_dir=default_dir,
            )
        )
        self.screen.set_input_placeholder(
            "Enter the path to your prepared structures directory."
        )

    def _on_manual_upload_submitted(self, data: dict) -> None:
        state = self.screen.app.current_state
        directory_str = (data.get("structures_dir") or "").strip()
        if not directory_str:
            self.screen.add_system_message(
                "Please provide a directory path containing your prepared structures.",
                "warning-text",
            )
            self._show_manual_upload_panel()
            return

        directory = Path(directory_str).expanduser().resolve()
        if not directory.is_dir():
            self.screen.add_system_message(
                f"Not a directory: {directory}", "error-text"
            )
            self._show_manual_upload_panel()
            return

        recommendation = state.context.docking_recommendation
        recommendation.structures_dir = str(directory)
        top_k, top_candidates = _top_k_bundle(state)
        candidate_ids = [
            _candidate_id(cand, i)
            for i, cand in enumerate(top_candidates)
        ]
        matches = scan_structure_directory(directory, candidate_ids)
        missing = [cid for cid in candidate_ids if cid not in matches]
        if missing:
            self.screen.add_system_message(
                f"Missing structure files for: {', '.join(missing[:5])}"
                + ("" if len(missing) <= 5 else f", \u2026 ({len(missing)} total)")
                + "\nExpected files named cand_<id>.pdb or cand_<id>.pdbqt.",
                "warning-text",
            )
            self._show_manual_upload_panel()
            return

        try:
            receptor_paths, grid_boxes = self._prepare_receptors_from_disk(
                state, matches, directory
            )
        except Exception as exc:
            self.screen.add_system_message(
                f"Failed to prepare receptors: {exc}", "error-text"
            )
            self._show_manual_upload_panel()
            return

        _apply_docking_plan(
            state,
            receptor_paths=receptor_paths,
            grid_boxes=grid_boxes,
            source="manual",
            top_k=top_k,
        )
        record_tertiary_structure_context(
            state,
            provider="manual",
            receptor_source="manual_upload",
            receptor_status="provided",
            result_path=str(directory),
            error="",
        )
        self.screen.app.save_state()
        self.screen.add_system_message(
            f"Loaded {len(receptor_paths)} per-candidate receptor PDBQTs from {directory}."
        )
        self._show_param_panel()

    def _prepare_receptors_from_disk(
        self,
        state: Any,
        matches: dict[str, dict[str, str]],
        target_dir: Path,
    ) -> tuple[dict[str, str], dict[str, dict[str, list[float]]]]:
        prep = self._receptor_prep_adapter()
        receptor_paths: dict[str, str] = {}
        grid_boxes: dict[str, dict[str, list[float]]] = {}
        padding = (
            state.docking_plan.grid_padding_angstrom
            if state.docking_plan is not None
            else DEFAULT_GRID_PADDING_ANGSTROM
        )
        for cand_id, files in matches.items():
            pdbqt = files.get("pdbqt")
            if pdbqt is None:
                pdb = files.get("pdb")
                if pdb is None:
                    raise RuntimeError(f"No structure file for {cand_id}")
                out = target_dir / f"{cand_id}.pdbqt"
                pdbqt = str(prep.prepare_pdbqt(pdb, out))
            receptor_paths[cand_id] = pdbqt
            box = prep.compute_box(pdbqt, padding=padding)
            grid_boxes[cand_id] = box.as_dict()
        return receptor_paths, grid_boxes

    # ------------------------------------------------------------------
    # Phase 3b: RNAComposer auto-mode worker
    # ------------------------------------------------------------------

    def _rnacomposer_worker(
        self,
        candidates: list[tuple[str, str]],
        structures_dir: Path,
    ) -> None:
        state = self.screen.app.current_state
        recommendation = state.context.docking_recommendation
        receptor_paths: dict[str, str] = {}
        grid_boxes: dict[str, dict[str, list[float]]] = {}
        prep = self._receptor_prep_adapter()
        adapter = getattr(self.screen.app, "tertiary_structure_adapter", None)
        if adapter is None:
            self.screen.app.call_from_thread(
                self.screen.add_system_message,
                "RNAComposer adapter is not configured; switch to manual upload.",
                "error-text",
            )
            self.screen.app.call_from_thread(self.screen.set_input_enabled, True)
            return

        total = len(candidates)
        completed = 0
        try:
            for cand_id, sequence in candidates:
                if self._rnacomposer_cancel.is_set():
                    break
                self._update_rnacomposer_progress(completed, total, cand_id)
                try:
                    rna_seq = prep.dna_to_rna(sequence)
                    pdb_path = adapter.predict_to_path(
                        rna_seq,
                        secondary_structure="",
                        output_dir=structures_dir,
                        candidate_id=cand_id,
                    )
                except Exception as exc:
                    self.screen.app.call_from_thread(
                        self.screen.add_system_message,
                        f"RNAComposer failed for {cand_id}: {exc}",
                        "error-text",
                    )
                    record_tertiary_structure_context(
                        state,
                        provider="rnacomposer",
                        receptor_source="rnacomposer",
                        receptor_status="failed",
                        error=str(exc),
                    )
                    return

                target_pdb = structures_dir / f"{cand_id}.pdb"
                pdb_text = prep.revert_ribose_to_deoxyribose(
                    Path(pdb_path).read_text(encoding="utf-8")
                )
                target_pdb.write_text(pdb_text, encoding="utf-8")
                pdbqt_path = structures_dir / f"{cand_id}.pdbqt"
                prep.prepare_pdbqt(target_pdb, pdbqt_path, treat_as_dna=False)
                receptor_paths[cand_id] = str(pdbqt_path)
                box = prep.compute_box(pdbqt_path, padding=(
                    state.docking_plan.grid_padding_angstrom
                    if state.docking_plan is not None
                    else DEFAULT_GRID_PADDING_ANGSTROM
                ))
                grid_boxes[cand_id] = box.as_dict()
                completed += 1
                self._update_rnacomposer_progress(completed, total, "")
        except Exception as exc:
            self.screen.app.call_from_thread(
                self.screen.add_system_message,
                f"RNAComposer worker error: {exc}",
                "error-text",
            )
            return

        if self._rnacomposer_cancel.is_set():
            self.screen.app.call_from_thread(
                self.screen.add_system_message,
                f"RNAComposer cancelled after {completed}/{total} candidates.",
                "warning-text",
            )
            self.screen.app.call_from_thread(self._show_strategy_panel)
            return

        _apply_docking_plan(
            state,
            receptor_paths=receptor_paths,
            grid_boxes=grid_boxes,
            source="rnacomposer",
            top_k=total,
        )
        record_tertiary_structure_context(
            state,
            provider="rnacomposer",
            receptor_source="rnacomposer",
            receptor_status="completed",
            result_path=str(structures_dir),
            error="",
        )
        self.screen.app.call_from_thread(self.screen.app.save_state)
        self.screen.app.call_from_thread(
            self.screen.add_system_message,
            f"RNAComposer prepared {total} per-candidate PDBQTs in {structures_dir}.",
        )
        self.screen.app.call_from_thread(self._show_param_panel)

    def _update_rnacomposer_progress(
        self,
        completed: int,
        total: int,
        current: str,
    ) -> None:
        def _update() -> None:
            widget = getattr(self.screen, "_active_structured_widget", None)
            if isinstance(widget, DockingRNAComposerProgressPanel):
                widget.update_progress(
                    completed=completed,
                    total=total,
                    current_candidate=current,
                )

        self.screen.app.call_from_thread(_update)

    # ------------------------------------------------------------------
    # Phase 4: read-only confirmation
    # ------------------------------------------------------------------

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
                machine_profile=plan.machine_profile or self._machine_profile(state),
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
            f"Docking plan: top-{plan.recommended_top_k} candidates, "
            f"{len(plan.receptor_paths)} receptors, exhaustiveness={plan.exhaustiveness}."
        )
        ns = next_step(Step.DOCKING_SELECTION)
        if ns:
            self.screen.advance_to_step(ns)

    # ------------------------------------------------------------------
    # Cover-aptamer recompute
    # ------------------------------------------------------------------

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
        self.screen.advance_to_step(Step.SPATIAL_RANK)

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

    @staticmethod
    def _machine_profile(state: Any) -> dict[str, Any]:
        return _machine_profile(state)
