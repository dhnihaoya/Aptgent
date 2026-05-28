"""Phase 3 mixin: structure preparation (manual upload + RNAComposer worker)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from aptgent.adapters.receptor_prep import scan_structure_directory
from aptgent.tui.steps.common import DEFAULT_GRID_PADDING_ANGSTROM
from aptgent.tui.widgets.structured_input import (
    DockingManualUploadPanel,
    DockingRNAComposerProgressPanel,
)
from aptgent.workflow.context import record_tertiary_structure_context

from ._helpers import (
    _apply_docking_plan,
    _candidate_id,
    _top_k_bundle,
)


class _StructuresMixin:
    """Phase 3: manual upload or RNAComposer auto-mode."""

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
            self._report_error(
                "RNAComposer adapter is not configured; switch to manual upload."
            )
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

                    def _on_poll(poll_count: int, elapsed: float) -> None:
                        self._update_rnacomposer_progress(
                            completed, total, cand_id, elapsed_seconds=elapsed,
                        )

                    pdb_path = adapter.predict_to_path(
                        rna_seq,
                        secondary_structure="",
                        output_dir=structures_dir,
                        candidate_id=cand_id,
                        on_poll=_on_poll,
                    )
                except Exception as exc:
                    self._threadsafe(
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
            self._threadsafe(
                self.screen.add_system_message,
                f"RNAComposer worker error: {exc}",
                "error-text",
            )
            return

        if self._rnacomposer_cancel.is_set():
            self._threadsafe(
                self.screen.add_system_message,
                f"RNAComposer cancelled after {completed}/{total} candidates.",
                "warning-text",
            )
            self._threadsafe(self._show_strategy_panel)
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
        self._threadsafe(self.screen.app.save_state)
        self._threadsafe(
            self.screen.add_system_message,
            f"RNAComposer prepared {total} per-candidate PDBQTs in {structures_dir}.",
        )
        self._threadsafe(self._show_param_panel)

    def _update_rnacomposer_progress(
        self,
        completed: int,
        total: int,
        current: str,
        *,
        elapsed_seconds: float | None = None,
    ) -> None:
        def _update() -> None:
            widget = getattr(self.screen, "_active_structured_widget", None)
            if isinstance(widget, DockingRNAComposerProgressPanel):
                widget.update_progress(
                    completed=completed,
                    total=total,
                    current_candidate=current,
                    elapsed_seconds=elapsed_seconds,
                )

        self._threadsafe(_update)
