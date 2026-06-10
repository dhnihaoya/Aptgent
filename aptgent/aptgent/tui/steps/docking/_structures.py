"""Phase 3 mixin: structure preparation (manual upload + RNAComposer worker)."""
from __future__ import annotations

import concurrent.futures
import time
from pathlib import Path
from typing import Any

from aptgent.adapters.receptor_prep import scan_structure_directory
from aptgent.tui.steps.common import DEFAULT_GRID_PADDING_ANGSTROM
from aptgent.tui.widgets.structured_input import (
    DockingManualUploadPanel,
    DockingMOEProgressPanel,
    DockingRNAComposerProgressPanel,
)
from aptgent.workflow.context import record_tertiary_structure_context

from ._helpers import (
    _apply_docking_plan,
    _candidate_id,
    _filtered_top_k_bundle,
)


class _StructuresMixin:
    """Phase 3: manual upload or RNAComposer auto-mode."""

    # RNAComposer is a public scraper whose individual jobs fail intermittently
    # (server load / one-off 5xx / slow queue). A second attempt absorbs most
    # transient hiccups so a single failure does not permanently drop a
    # candidate. Each job already spends minutes polling, so an immediate
    # retry adds negligible extra load; the delay stays at 0 by default.
    _RNACOMPOSER_RETRY_ATTEMPTS = 2
    _RNACOMPOSER_RETRY_DELAY_SECONDS = 0.0

    def _predict_rnacomposer_with_retry(
        self,
        adapter: Any,
        rna_seq: str,
        structures_dir: Path,
        cand_id: str,
        on_poll: Any,
    ) -> str:
        """Call ``predict_to_path`` with a small retry on transient failures.

        Re-raises the last exception once attempts are exhausted so callers can
        log/record the failure exactly as before. Cancellation short-circuits
        immediately without further retries.
        """
        last_exc: Exception | None = None
        for attempt in range(self._RNACOMPOSER_RETRY_ATTEMPTS):
            if self._rnacomposer_cancel.is_set():
                raise RuntimeError("cancelled")
            try:
                return adapter.predict_to_path(
                    rna_seq,
                    secondary_structure="",
                    output_dir=structures_dir,
                    candidate_id=cand_id,
                    on_poll=on_poll,
                )
            except Exception as exc:  # noqa: BLE001 — retried below
                if self._rnacomposer_cancel.is_set():
                    raise
                last_exc = exc
                if (
                    attempt + 1 < self._RNACOMPOSER_RETRY_ATTEMPTS
                    and self._RNACOMPOSER_RETRY_DELAY_SECONDS > 0
                ):
                    time.sleep(self._RNACOMPOSER_RETRY_DELAY_SECONDS)
        assert last_exc is not None
        raise last_exc

    def _show_manual_upload_panel(self) -> None:
        state = self.screen.app.current_state
        recommendation = state.context.docking_recommendation
        top_k, top_candidates = _filtered_top_k_bundle(
            state, mutation_ratio=recommendation.mutation_ratio,
        )
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
        top_k, top_candidates = _filtered_top_k_bundle(
            state, mutation_ratio=recommendation.mutation_ratio,
        )
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
        """RNAComposer fetch + Open Babel post-processing (pipelined)."""
        prep = self._receptor_prep_adapter()
        state = self.screen.app.current_state

        def _postprocess_openbabel(cand_id: str) -> tuple[str, dict[str, list[float]]]:
            source_pdb = structures_dir / f"{cand_id}.pdb"
            target_pdb = structures_dir / f"{cand_id}.dna.pdb"
            pdb_text = prep.revert_ribose_to_deoxyribose(
                source_pdb.read_text(encoding="utf-8")
            )
            target_pdb.write_text(pdb_text, encoding="utf-8")
            minimized_pdb = structures_dir / f"{cand_id}.min.pdb"
            prep.energy_minimize(target_pdb, minimized_pdb)
            pdbqt_path = structures_dir / f"{cand_id}.pdbqt"
            prep.prepare_pdbqt(minimized_pdb, pdbqt_path, treat_as_dna=False)
            box = prep.compute_box(pdbqt_path, padding=(
                state.docking_plan.grid_padding_angstrom
                if state.docking_plan is not None
                else DEFAULT_GRID_PADDING_ANGSTROM
            ))
            return str(pdbqt_path), box.as_dict()

        self._run_rnacomposer_pipeline(
            candidates,
            structures_dir,
            postprocess_one=_postprocess_openbabel,
            source="rnacomposer",
            provider="rnacomposer",
            completed_message=(
                "RNAComposer prepared {done}/{total} per-candidate PDBQTs in "
                + str(structures_dir) + "."
            ),
        )

    def _run_rnacomposer_pipeline(
        self,
        candidates: list[tuple[str, str]],
        structures_dir: Path,
        *,
        postprocess_one: Any,
        source: str,
        provider: str,
        completed_message: str,
    ) -> None:
        """Shared RNAComposer fetch→post-process pipeline.

        Fetches each candidate from RNAComposer while post-processing the
        previous one in the foreground (and prefetching the next in a
        background thread), so the slow network fetch overlaps with local
        structure preparation.  ``postprocess_one(cand_id)`` converts one
        fetched RNA PDB into a docking-ready receptor and returns
        ``(pdbqt_path, grid_box_dict)``; it is the only part that differs
        between the Open Babel and MOE strategies.
        """
        state = self.screen.app.current_state
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
        if total == 0:
            self._threadsafe(
                self.screen.add_system_message,
                "No candidates to submit to RNAComposer.",
                "warning-text",
            )
            self._threadsafe(self._show_strategy_panel)
            return

        fetched_count = 0
        postprocessed_count = 0

        # -- helpers -------------------------------------------------------

        def _fetch_one(cand_id: str, sequence: str) -> str | None:
            if self._rnacomposer_cancel.is_set():
                return None
            rna_seq = prep.dna_to_rna(sequence)

            def _on_poll(poll_count: int, elapsed: float) -> None:
                if self._rnacomposer_cancel.is_set():
                    raise RuntimeError("cancelled")
                self._update_rnacomposer_progress(
                    fetched=fetched_count,
                    postprocessed=postprocessed_count,
                    total=total,
                    fetching_candidate=cand_id,
                    fetching_elapsed=elapsed,
                )

            try:
                self._predict_rnacomposer_with_retry(
                    adapter, rna_seq, structures_dir, cand_id, _on_poll,
                )
            except Exception as exc:
                if self._rnacomposer_cancel.is_set():
                    return None
                self._threadsafe(
                    self.screen.add_system_message,
                    f"RNAComposer failed for {cand_id}: {exc}",
                    "error-text",
                )
                record_tertiary_structure_context(
                    state,
                    provider=provider,
                    receptor_source=source,
                    receptor_status="failed",
                    error=str(exc),
                )
                return None
            return cand_id

        def _postprocess(cand_id: str) -> None:
            nonlocal postprocessed_count
            pdbqt_path, box = postprocess_one(cand_id)
            # Commit only after all steps succeed
            receptor_paths[cand_id] = pdbqt_path
            grid_boxes[cand_id] = box
            postprocessed_count += 1

        # -- pipeline loop -------------------------------------------------

        candidate_ready = [False] * total

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                # Fetch first candidate synchronously
                first_id, first_seq = candidates[0]
                self._update_rnacomposer_progress(
                    fetched=0, postprocessed=0, total=total,
                    fetching_candidate=first_id,
                )
                result = _fetch_one(first_id, first_seq)
                if result is not None:
                    candidate_ready[0] = True
                fetched_count = 1

                fetch_future: concurrent.futures.Future | None = None

                for i in range(total):
                    if self._rnacomposer_cancel.is_set():
                        break

                    cand_id, sequence = candidates[i]

                    # Start fetching next candidate in background
                    if i + 1 < total:
                        next_id, next_seq = candidates[i + 1]
                        fetch_future = executor.submit(
                            _fetch_one, next_id, next_seq,
                        )

                    # Post-process current candidate (only if fetch succeeded)
                    if candidate_ready[i]:
                        self._update_rnacomposer_progress(
                            fetched=fetched_count,
                            postprocessed=postprocessed_count,
                            total=total,
                            postprocessing_candidate=cand_id,
                        )
                        try:
                            _postprocess(cand_id)
                        except Exception as exc:
                            candidate_ready[i] = False
                            self._threadsafe(
                                self.screen.add_system_message,
                                f"Post-processing failed for {cand_id}: {exc}",
                                "error-text",
                            )
                            record_tertiary_structure_context(
                                state,
                                provider=provider,
                                receptor_source=source,
                                receptor_status="failed",
                                error=str(exc),
                            )
                        self._update_rnacomposer_progress(
                            fetched=fetched_count,
                            postprocessed=postprocessed_count,
                            total=total,
                        )

                    # Wait for next fetch to complete
                    if fetch_future is not None:
                        try:
                            result = fetch_future.result()
                        except Exception:
                            result = None
                        fetch_future = None
                        if result is not None:
                            candidate_ready[i + 1] = True
                        fetched_count = i + 2

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
                f"RNAComposer cancelled after {postprocessed_count}/{total} candidates.",
                "warning-text",
            )
            self._threadsafe(self._show_strategy_panel)
            return

        if postprocessed_count == 0:
            self._threadsafe(
                self.screen.add_system_message,
                f"All {total} RNAComposer predictions failed.",
                "error-text",
            )
            self._threadsafe(self._show_strategy_panel)
            return

        failed_count = total - postprocessed_count
        if failed_count > 0:
            self._threadsafe(
                self.screen.add_system_message,
                f"RNAComposer: {failed_count}/{total} candidates failed, "
                f"proceeding with {postprocessed_count} successful.",
                "warning-text",
            )

        _apply_docking_plan(
            state,
            receptor_paths=receptor_paths,
            grid_boxes=grid_boxes,
            source=source,
            top_k=postprocessed_count,
        )
        record_tertiary_structure_context(
            state,
            provider=provider,
            receptor_source=source,
            receptor_status="completed",
            result_path=str(structures_dir),
            error="",
        )
        self._threadsafe(self.screen.app.save_state)
        self._threadsafe(
            self.screen.add_system_message,
            completed_message.format(done=postprocessed_count, total=total),
        )
        self._threadsafe(self._show_param_panel)

    def _update_rnacomposer_progress(
        self,
        fetched: int,
        postprocessed: int,
        total: int,
        *,
        fetching_candidate: str = "",
        fetching_elapsed: float | None = None,
        postprocessing_candidate: str = "",
    ) -> None:
        def _update() -> None:
            widget = getattr(self.screen, "_active_structured_widget", None)
            if isinstance(widget, DockingRNAComposerProgressPanel):
                widget.update_pipeline_progress(
                    fetched=fetched,
                    postprocessed=postprocessed,
                    total=total,
                    fetching_candidate=fetching_candidate,
                    fetching_elapsed=fetching_elapsed,
                    postprocessing_candidate=postprocessing_candidate,
                )

        self._threadsafe(_update)

    def _update_moe_progress(self, *, done: int, total: int) -> None:
        def _update() -> None:
            widget = getattr(self.screen, "_active_structured_widget", None)
            if isinstance(widget, DockingMOEProgressPanel):
                widget.update_progress(done=done, total=total)

        self._threadsafe(_update)

    # ------------------------------------------------------------------
    # MOE helpers
    # ------------------------------------------------------------------

    def _convert_moe_results_to_pdbqt(
        self,
        moe_results: dict[str, Path],
        structures_dir: Path,
        state: Any,
    ) -> tuple[dict[str, str], dict[str, dict[str, list[float]]], int]:
        """Convert MOE-output DNA PDBs to PDBQT + compute grid boxes.

        Returns (receptor_paths, grid_boxes, postprocessed_count).
        Partial failures are logged individually; only successful conversions
        are included in the results.
        """
        from aptgent.adapters.moe_prep import MoePreparationAdapter

        moe_adapter: MoePreparationAdapter = self.screen.app.moe_prep_adapter
        receptor_paths: dict[str, str] = {}
        grid_boxes: dict[str, dict[str, list[float]]] = {}
        postprocessed_count = 0

        for cand_id, moe_pdb in moe_results.items():
            try:
                pdbqt_path = structures_dir / f"{cand_id}.pdbqt"
                moe_adapter.prepare_pdbqt(moe_pdb, pdbqt_path)
                box = moe_adapter.compute_box(pdbqt_path, padding=(
                    state.docking_plan.grid_padding_angstrom
                    if state.docking_plan is not None
                    else DEFAULT_GRID_PADDING_ANGSTROM
                ))
                receptor_paths[cand_id] = str(pdbqt_path)
                grid_boxes[cand_id] = box.as_dict()
                postprocessed_count += 1
            except Exception as exc:
                self._threadsafe(
                    self.screen.add_system_message,
                    f"PDBQT conversion failed for {cand_id}: {exc}",
                    "error-text",
                )

        return receptor_paths, grid_boxes, postprocessed_count

    # ------------------------------------------------------------------
    # MOE combined (RNAComposer + MOE)
    # ------------------------------------------------------------------

    def _moe_combined_worker(
        self,
        candidates: list[tuple[str, str]],
        structures_dir: Path,
    ) -> None:
        """RNAComposer fetch + MOE RNA->DNA+minimize, pipelined per candidate.

        MOE used to require every structure on disk before its single batch
        run; now that MOE is invoked per file we process each structure as
        soon as it is fetched, overlapping the slow RNAComposer network fetch
        of the next candidate with the local MOE run of the current one.
        """
        from aptgent.adapters.moe_prep import MoePreparationAdapter

        moe_adapter: MoePreparationAdapter = self.screen.app.moe_prep_adapter
        state = self.screen.app.current_state
        moe_output_dir = structures_dir / "moe_output"

        def _postprocess_moe(cand_id: str) -> tuple[str, dict[str, list[float]]]:
            # One isolated moebatch run for this single fetched structure.
            # Progress is shown via the panel's post-processing bar, so no
            # per-file chat messages here (would be one line per candidate).
            moe_results = moe_adapter.convert_rna_to_dna_minimize(
                input_dir=structures_dir,
                output_dir=moe_output_dir,
                candidate_ids=[cand_id],
            )
            moe_pdb = moe_results[cand_id]
            pdbqt_path = structures_dir / f"{cand_id}.pdbqt"
            moe_adapter.prepare_pdbqt(moe_pdb, pdbqt_path)
            box = moe_adapter.compute_box(pdbqt_path, padding=(
                state.docking_plan.grid_padding_angstrom
                if state.docking_plan is not None
                else DEFAULT_GRID_PADDING_ANGSTROM
            ))
            return str(pdbqt_path), box.as_dict()

        self._run_rnacomposer_pipeline(
            candidates,
            structures_dir,
            postprocess_one=_postprocess_moe,
            source="rnacomposer-moe",
            provider="rnacomposer+moe",
            completed_message=(
                "RNAComposer + MOE prepared {done}/{total} receptor PDBQTs."
            ),
        )

    # ------------------------------------------------------------------
    # MOE manual (user-provided RNA PDBs)
    # ------------------------------------------------------------------

    def _moe_manual_worker(
        self,
        rna_dir: Path,
        structures_dir: Path,
        candidate_ids: list[str],
    ) -> None:
        """MOE batch processing of user-provided RNA PDB files."""
        from aptgent.adapters.moe_prep import MoePreparationAdapter

        state = self.screen.app.current_state
        moe_adapter: MoePreparationAdapter = self.screen.app.moe_prep_adapter

        total = len(candidate_ids)

        def _moe_file_done(done: int, moe_total: int) -> None:
            self._update_moe_progress(done=done, total=moe_total)

        try:
            moe_results = moe_adapter.convert_rna_to_dna_minimize(
                input_dir=rna_dir,
                output_dir=structures_dir / "moe_output",
                candidate_ids=candidate_ids,
                on_progress=lambda msg: self._threadsafe(
                    self.screen.add_system_message, msg
                ),
                on_file_done=_moe_file_done,
            )
        except Exception as exc:
            self._threadsafe(
                self.screen.add_system_message,
                f"MOE processing failed: {exc}",
                "error-text",
            )
            self._threadsafe(self._show_strategy_panel)
            return

        if self._rnacomposer_cancel.is_set():
            self._threadsafe(
                self.screen.add_system_message,
                "MOE cancelled; returning to strategy panel.",
                "warning-text",
            )
            self._threadsafe(self._show_strategy_panel)
            return

        receptor_paths, grid_boxes, postprocessed_count = (
            self._convert_moe_results_to_pdbqt(moe_results, structures_dir, state)
        )

        if postprocessed_count == 0:
            self._threadsafe(
                self.screen.add_system_message,
                "All PDBQT conversions failed.",
                "error-text",
            )
            self._threadsafe(self._show_strategy_panel)
            return

        _apply_docking_plan(
            state,
            receptor_paths=receptor_paths,
            grid_boxes=grid_boxes,
            source="moe-manual",
            top_k=postprocessed_count,
        )
        record_tertiary_structure_context(
            state,
            provider="moe",
            receptor_source="moe-manual",
            receptor_status="completed",
            result_path=str(rna_dir),
            error="",
        )
        self._threadsafe(self.screen.app.save_state)
        self._threadsafe(
            self.screen.add_system_message,
            f"MOE prepared {postprocessed_count}/{total} receptor PDBQTs.",
        )
        self._threadsafe(self._show_param_panel)

    # ------------------------------------------------------------------
    # MOE manual upload panel
    # ------------------------------------------------------------------

    def _show_moe_manual_upload_panel(self) -> None:
        state = self.screen.app.current_state
        recommendation = state.context.docking_recommendation
        default_dir = recommendation.structures_dir or str(
            self.screen.app.persistence.run_dir(state.run_id)
            / "docking" / "rna_structures"
        )
        _, top_candidates = _filtered_top_k_bundle(
            state, mutation_ratio=state.context.docking_recommendation.mutation_ratio,
        )
        candidate_ids = [
            _candidate_id(cand, i)
            for i, cand in enumerate(top_candidates)
        ]
        self.screen.add_structured_widget(
            DockingManualUploadPanel(
                export_dir="",
                candidate_ids=candidate_ids,
                default_structures_dir=default_dir,
                phase="moe_manual_upload",
            )
        )
        self.screen.set_input_placeholder(
            "Enter the path to your directory containing RNA PDB files."
        )

    def _on_moe_manual_upload_submitted(self, data: dict) -> None:
        state = self.screen.app.current_state
        directory_str = (data.get("structures_dir") or "").strip()
        if not directory_str:
            self.screen.add_system_message(
                "Please provide a directory path containing RNA PDB files.",
                "warning-text",
            )
            self._show_moe_manual_upload_panel()
            return

        directory = Path(directory_str).expanduser().resolve()
        if not directory.is_dir():
            self.screen.add_system_message(
                f"Not a directory: {directory}", "error-text"
            )
            self._show_moe_manual_upload_panel()
            return

        _, top_candidates = _filtered_top_k_bundle(
            state, mutation_ratio=state.context.docking_recommendation.mutation_ratio,
        )
        candidate_ids = [
            _candidate_id(cand, i)
            for i, cand in enumerate(top_candidates)
        ]

        # Check for RNA PDB files
        found = [cid for cid in candidate_ids if (directory / f"{cid}.pdb").exists()]
        if not found:
            expected = f" (e.g. {candidate_ids[0]}.pdb)" if candidate_ids else ""
            self.screen.add_system_message(
                f"No matching PDB files found in {directory}. "
                f"Expected files named <candidate_id>.pdb{expected}.",
                "error-text",
            )
            self._show_moe_manual_upload_panel()
            return

        structures_dir = Path(
            state.context.docking_recommendation.structures_dir
            or str(self.screen.app.persistence.run_dir(state.run_id) / "docking" / "structures")
        )
        structures_dir.mkdir(parents=True, exist_ok=True)

        self._rnacomposer_cancel.clear()
        self.run_worker(
            lambda: self._moe_manual_worker(directory, structures_dir, found),
            activity="Running MOE on uploaded RNA structures...",
        )
        self.screen.add_structured_widget(
            DockingMOEProgressPanel(total=len(found))
        )
