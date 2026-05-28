"""Phase 2 mixin: source selection (manual upload vs RNAComposer)."""
from __future__ import annotations

from aptgent.domain.models import DockingPlan
from aptgent.tui.widgets.structured_input import (
    DockingRNAComposerProgressPanel,
    DockingSourcePanel,
)

from ._helpers import _candidate_id, _top_k_bundle


class _SourceMixin:
    """Phase 2: choose receptor source."""

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
            from aptgent.adapters.receptor_prep import export_top_k_sequences
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
