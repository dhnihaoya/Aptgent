"""Phase 2 mixin: source selection (manual upload vs RNAComposer)."""
from __future__ import annotations

from aptgent.domain.models import DockingPlan
from aptgent.tui.widgets.structured_input import (
    DockingMOEProgressPanel,
    DockingRNAComposerProgressPanel,
    DockingSourcePanel,
)

from ._helpers import _candidate_id, _filtered_top_k_bundle, _top_k_bundle


def _docking_param_summary(plan: DockingPlan) -> str:
    """Format a brief read-only summary of confirmed docking parameters."""
    timeout_text = (
        f"{plan.per_ligand_timeout_seconds} s"
        if plan.per_ligand_timeout_seconds is not None
        else "config default"
    )
    seed_text = (
        str(plan.seed) if plan.seed is not None else "unset (Vina random)"
    )
    budget_text = (
        f"{plan.time_budget} h" if plan.time_budget is not None else "not set"
    )
    return (
        f"Docking parameters confirmed:\n"
        f"• Candidates to dock: [bold]{plan.recommended_top_k}[/]\n"
        f"• affinity_top_k: [bold]{plan.affinity_top_k}[/]\n"
        f"• exhaustiveness: [bold]{plan.exhaustiveness}[/]\n"
        f"• num_modes: [bold]{plan.num_modes}[/]\n"
        f"• energy_range: [bold]{plan.energy_range}[/] kcal/mol\n"
        f"• grid padding: [bold]{plan.grid_padding_angstrom}[/] Å\n"
        f"• per-ligand timeout: [bold]{timeout_text}[/]\n"
        f"• time budget (advisory): [bold]{budget_text}[/]\n"
        f"• seed: [bold]{seed_text}[/]"
    )


class _SourceMixin:
    """Phase 2: choose receptor source."""

    def _show_source_panel(self) -> None:
        state = self.screen.app.current_state
        recommendation = state.context.docking_recommendation
        top_k, _ = _filtered_top_k_bundle(
            state, mutation_ratio=recommendation.mutation_ratio,
        )
        moe_available = self._is_moe_available()
        self.screen.add_structured_widget(
            DockingSourcePanel(top_k=top_k, moe_available=moe_available)
        )
        self.screen.set_input_placeholder(
            "Choose how the per-candidate structures will be prepared."
        )

    def _on_source_selected(self, source: str) -> None:
        state = self.screen.app.current_state
        recommendation = state.context.docking_recommendation
        top_k, top_candidates = _filtered_top_k_bundle(
            state, mutation_ratio=recommendation.mutation_ratio,
        )

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
                _docking_param_summary(state.docking_plan),
            )
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
            # When MOE is available the "RNAComposer" choice automatically
            # routes through RNAComposer + MOE (RNA→DNA + AmberEHT minimize);
            # otherwise it falls back to RNAComposer + Open Babel.
            use_moe = self._is_moe_available()
            recommendation.phase = "preparing"
            recommendation.strategy = "rnacomposer-moe" if use_moe else "rnacomposer"
            state.docking_plan.receptor_source = recommendation.strategy
            structures_dir.mkdir(parents=True, exist_ok=True)
            self.screen.app.save_state()
            self.screen.add_system_message(
                _docking_param_summary(state.docking_plan),
            )
            self._rnacomposer_cancel.clear()
            seq_pairs = [
                (_candidate_id(cand, i), cand.sequence)
                for i, cand in enumerate(top_candidates)
            ]
            if use_moe:
                self.run_worker(
                    lambda: self._moe_combined_worker(seq_pairs, structures_dir),
                    activity="Submitting candidates to RNAComposer + MOE...",
                )
                self.screen.add_structured_widget(
                    DockingRNAComposerProgressPanel(total=len(top_candidates))
                )
            else:
                self.run_worker(
                    lambda: self._rnacomposer_worker(seq_pairs, structures_dir),
                    activity="Submitting candidates to RNAComposer...",
                )
                self.screen.add_structured_widget(
                    DockingRNAComposerProgressPanel(
                        total=len(top_candidates),
                    )
                )
            return

        if source == "rnacomposer-moe":
            recommendation.phase = "preparing"
            recommendation.strategy = "rnacomposer-moe"
            structures_dir.mkdir(parents=True, exist_ok=True)
            self.screen.app.save_state()
            self.screen.add_system_message(
                _docking_param_summary(state.docking_plan),
            )
            self._rnacomposer_cancel.clear()
            self.run_worker(
                lambda: self._moe_combined_worker(
                    [
                        (_candidate_id(cand, i), cand.sequence)
                        for i, cand in enumerate(top_candidates)
                    ],
                    structures_dir,
                ),
                activity="Submitting candidates to RNAComposer + MOE...",
            )
            self.screen.add_structured_widget(
                DockingMOEProgressPanel(total=len(top_candidates))
            )
            return

        if source == "moe-manual":
            recommendation.phase = "awaiting_moe_structures"
            recommendation.strategy = "moe-manual"
            self.screen.app.save_state()
            self.screen.add_system_message(
                _docking_param_summary(state.docking_plan),
            )
            self._show_moe_manual_upload_panel()
            return

    def _is_moe_available(self) -> bool:
        return getattr(self.screen.app, "moe_prep_adapter", None) is not None
