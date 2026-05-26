"""Docking selection step handler.

Implements the multi-phase docking setup described in
Aptamers-2026.5.4.docx §2.4.4:

1. **topk_selection** \u2013 pick how many top candidates to dock (paper used 5).
2. **source_selection** \u2013 choose receptor source: manual upload vs.
   automated RNAComposer scraping.
3. **structure_preparation** \u2013 either prompt the user for a structures
   directory or stream RNAComposer progress; in both cases we end up with
   per-candidate PDBQT files and bounding boxes.
4. **param_confirmation** \u2013 confirm Vina defaults (exhaustiveness 8,
   num_modes 9, energy_range 3.0) and submit.
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
from aptgent.domain.enums import Step
from aptgent.domain.models import DockingPlan, GridBox
from aptgent.llm.skills import DockingPlannerSkill
from aptgent.tui.steps.base import StepHandler
from aptgent.tui.steps.common import (
    compute_deterministic_docking_plan,
    format_docking_recommendation_markdown,
    next_step,
    run_llm_interaction,
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
    top_k = state.context.docking_recommendation.recommended_top_k or 5
    return top_k, list(state.candidates[:top_k])


def _machine_profile(state: Any) -> dict[str, Any]:
    recommendation = state.context.docking_recommendation
    profile = recommendation.machine_profile or HardwareProbeAdapter().probe()
    return dict(profile)


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
            self._show_topk_panel()

        self.screen.set_input_enabled(True)

    # ------------------------------------------------------------------
    # Free-text fallback
    # ------------------------------------------------------------------

    def handle_user_input(self, text: str) -> None:
        if "skip" in text.strip().lower():
            self._skip()

    # ------------------------------------------------------------------
    # Structured submissions
    # ------------------------------------------------------------------

    def handle_structured_input(self, data: dict) -> None:
        phase = data.get("phase")
        if phase == "topk_selected":
            self._on_topk_submitted(data)
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
        if action.startswith("llm-hint:"):
            self._on_llm_hint(action)
            return
        if action == "source:manual":
            self._on_source_selected("manual")
            return
        if action == "source:rnacomposer":
            self._on_source_selected("rnacomposer")
            return
        if action == "source:back":
            self._show_topk_panel()
            return
        if action == "rnacomposer:cancel":
            self._rnacomposer_cancel.set()
            self.screen.add_system_message(
                "Cancelling RNAComposer job; falling back to manual upload.",
                "warning-text",
            )
            self._show_topk_panel()
            return
        if action.startswith("cover-aptamer:"):
            self._cover_aptamer(action.split(":", 1)[1])
            return

    # ------------------------------------------------------------------
    # Phase 1: top-k selection
    # ------------------------------------------------------------------

    def _show_topk_panel(self) -> None:
        state = self.screen.app.current_state
        machine_profile = self._machine_profile(state)
        candidate_count = len(state.candidates)
        plan = compute_deterministic_docking_plan(
            candidate_count=candidate_count,
            machine_profile=machine_profile,
            time_budget_hours=state.time_budget,
        )
        recommendation = state.context.docking_recommendation
        existing_top_k = recommendation.recommended_top_k or plan["recommended_top_k"] or 5
        recommendation.phase = "initial"
        recommendation.machine_profile = machine_profile
        recommendation.candidate_count = candidate_count
        self.screen.app.save_state()
        self.screen.add_structured_widget(
            DockingStrategyPanel(
                machine_profile=machine_profile,
                time_budget=state.time_budget,
                candidate_count=candidate_count,
                default_top_k=existing_top_k,
            )
        )
        self.screen.set_input_placeholder(
            "Pick how many candidates to dock, then continue. Type 'skip' to skip docking."
        )

    def _on_topk_submitted(self, data: dict) -> None:
        state = self.screen.app.current_state
        candidate_count = len(state.candidates)
        try:
            top_k = int(str(data.get("top_k", "")).strip() or "5")
        except ValueError:
            self.screen.add_system_message(
                "Top-k must be an integer.", "warning-text"
            )
            self._show_topk_panel()
            return
        if top_k <= 0:
            self.screen.add_system_message("Top-k must be > 0.", "warning-text")
            self._show_topk_panel()
            return
        top_k = min(top_k, candidate_count or top_k)

        budget_raw = str(data.get("time_budget", "")).strip()
        time_budget = int(budget_raw) if budget_raw.isdigit() else state.time_budget

        recommendation = state.context.docking_recommendation
        recommendation.recommended_top_k = top_k
        recommendation.time_budget_hours = time_budget
        recommendation.phase = "topk_selected"
        state.time_budget = time_budget
        self.screen.app.save_state()
        self._show_source_panel()

    def _on_llm_hint(self, action: str) -> None:
        _, top_k_raw, budget_raw = action.split(":", 2)
        try:
            top_k_default = int(top_k_raw) if top_k_raw else 5
        except ValueError:
            top_k_default = 5
        time_budget = int(budget_raw) if budget_raw.isdigit() else None
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
                    ),
                    candidate_count=candidate_count,
                    machine_profile=machine_profile,
                    time_budget_hours=time_budget,
                    target_smiles=target_smiles,
                ),
            )
            top_k = result.get("recommended_top_k", top_k_default)
            exhaustiveness = result.get("recommended_exhaustiveness", 8)
            recommended_time = result.get("recommended_time_budget_hours")
            reason = result.get("reason", "")
            markdown = format_docking_recommendation_markdown(
                candidate_count=candidate_count,
                machine_profile=machine_profile,
                time_budget_hours=recommended_time,
                recommended_top_k=top_k,
                recommended_exhaustiveness=exhaustiveness,
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
            self.screen.app.call_from_thread(self._show_topk_panel)
        except Exception as exc:
            self.screen.app.call_from_thread(
                self.screen.add_system_message,
                f"LLM hint failed: {exc}",
                "error-text",
            )
            self.screen.app.call_from_thread(self._show_topk_panel)
        finally:
            self.screen.app.call_from_thread(self.screen.set_input_enabled, True)

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
            else 4.0
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
                    else 4.0
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
            self.screen.app.call_from_thread(self._show_topk_panel)
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
    # Phase 4: parameter confirmation
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
            self._show_topk_panel()
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
            self._show_topk_panel()
            return

        budget = data.get("time_budget")
        if isinstance(budget, str):
            budget = int(budget) if budget.isdigit() else None
        plan.time_budget = budget

        exh_raw = data.get("exhaustiveness")
        if isinstance(exh_raw, str):
            try:
                exh_raw = int(exh_raw)
            except ValueError:
                exh_raw = None
        if isinstance(exh_raw, int) and exh_raw > 0:
            plan.exhaustiveness = exh_raw

        padding_raw = data.get("grid_padding_angstrom")
        try:
            padding = float(padding_raw)
        except (TypeError, ValueError):
            padding = plan.grid_padding_angstrom
        plan.grid_padding_angstrom = padding

        recommendation = state.context.docking_recommendation
        recommendation.accepted = bool(data.get("accepted_recommendation"))
        recommendation.phase = "editing_form"
        state.time_budget = budget or state.time_budget
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
