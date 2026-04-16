from __future__ import annotations

from typing import Any, Callable

from aptgent.domain.enums import Step
from aptgent.domain.models import PdbAnalysisResult, PdbChainCandidate, PdbLigandCandidate
from aptgent.tui.steps.common import clean_text
from aptgent.tui.widgets.structured_input import PdbSelectionPanel
from aptgent.workflow.context import record_intake_context, record_pdb_intake_context


class PdbIntakeHelper:
    def __init__(
        self,
        screen: Any,
        *,
        resolve_and_complete: Callable[..., None],
        activate_general_retry: Callable[[str], None],
    ) -> None:
        self.screen = screen
        self._resolve_and_complete = resolve_and_complete
        self._activate_general_retry = activate_general_retry

    def analyze_pdb_intake(
        self,
        *,
        pdb_id: str,
        user_sequence: str | None,
        user_target_text: str | None,
        user_brief: str | None,
        modification_region: str | None,
        analogs: list[str],
        time_budget_hours: int | None,
    ) -> None:
        state = self.screen.app.current_state
        artifact_dir = self.screen.app.persistence.get_artifact_dir(state.run_id)

        try:
            record_pdb_intake_context(state, download_status="running", analysis_status="running")
            self.screen.app.call_from_thread(
                self.screen.add_tool_message,
                f"**PDB Intake Agent**\n\n- Starting analysis for `{pdb_id}`\n- Stage: download structure file",
                label="agent:pdb",
            )
            artifact_path = self.screen.app.pdb_analysis_adapter.fetch(pdb_id, artifact_dir)
            record_pdb_intake_context(
                state,
                download_status="completed",
                artifact_path=str(artifact_path),
            )
            self.screen.app.call_from_thread(
                self.screen.add_tool_message,
                f"**PDB Intake Agent**\n\n- Downloaded `{artifact_path.name}`\n- Stage: parse nucleic-acid chains and ligands",
                label="agent:pdb",
            )
            analysis = self.screen.app.pdb_analysis_adapter.analyze(pdb_id, artifact_path)
            analysis = self.review_pdb_analysis(analysis)
            record_pdb_intake_context(
                state,
                analysis_status="completed",
                title=analysis.title,
                chains=analysis.nucleic_acid_chains,
                ligands=analysis.ligands,
                recommended_chain_id=analysis.recommended_chain_id,
                recommended_ligand_key=analysis.recommended_ligand_key,
                semantic_validation_status=analysis.semantic_status,
                semantic_note=analysis.semantic_note,
                error=analysis.error,
            )
        except Exception as exc:
            message = f"PDB import failed for `{pdb_id}`: {exc}"
            record_pdb_intake_context(
                state,
                download_status="failed",
                analysis_status="failed",
                error=message,
            )
            self._activate_general_retry(message)
            return

        if not analysis.nucleic_acid_chains:
            self._activate_general_retry(
                f"PDB `{analysis.pdb_id}` did not contain a usable nucleic-acid chain."
            )
            return

        selected_chain = self.choose_chain(analysis, user_sequence)
        sequence_match_status = self.compare_sequence(
            user_sequence, selected_chain.sequence if selected_chain else None
        )
        if user_sequence and selected_chain and sequence_match_status == "mismatch":
            self.screen.app.call_from_thread(
                self.screen.add_tool_message,
                "\n".join(
                    [
                        "**Sequence reconciliation**",
                        "",
                        f"- User-provided sequence did not match PDB `{analysis.pdb_id}` chain `{selected_chain.chain_id}`.",
                        f"- The workflow will use the PDB-derived sequence: `{selected_chain.sequence}`",
                    ]
                ),
                label="agent:pdb",
            )

        selected_ligand: PdbLigandCandidate | None = None
        needs_selection = False

        if selected_chain is None:
            needs_selection = True
        if not user_target_text:
            if len(analysis.ligands) == 1:
                selected_ligand = analysis.ligands[0]
            elif len(analysis.ligands) > 1:
                needs_selection = True

        record_pdb_intake_context(
            state,
            derived_sequence=selected_chain.sequence if selected_chain else None,
            selected_chain_id=selected_chain.chain_id if selected_chain else None,
            selected_ligand_key=selected_ligand.key if selected_ligand else None,
            sequence_match_status=sequence_match_status,
            needs_user_selection=needs_selection,
        )

        if needs_selection:
            record_intake_context(
                state,
                phase="awaiting_pdb_selection",
                last_resolution_error=(
                    "Multiple chain and/or ligand candidates were detected in the imported structure."
                ),
            )
            self.screen.app.save_state()
            self.screen.app.call_from_thread(self.screen.advance_to_step, Step.INTAKE)
            return

        if selected_chain is None:
            self._activate_general_retry(
                f"PDB `{analysis.pdb_id}` did not yield a unique nucleic-acid chain."
            )
            return

        target_from_pdb = selected_ligand.display_name if selected_ligand else None
        self.finalize_pdb_import(
            analysis=analysis,
            chain=selected_chain,
            ligand=selected_ligand,
            target_text=user_target_text or target_from_pdb,
            user_brief=user_brief,
            modification_region=modification_region,
            analogs=analogs,
            time_budget_hours=time_budget_hours,
        )

    def review_pdb_analysis(self, analysis: PdbAnalysisResult) -> PdbAnalysisResult:
        if not analysis.nucleic_acid_chains:
            return analysis

        summary_lines = [
            f"PDB ID: {analysis.pdb_id}",
            f"Title: {analysis.title or 'unknown'}",
            "Nucleic-acid chains:",
        ]
        for chain in analysis.nucleic_acid_chains:
            summary_lines.append(
                f"- chain {chain.chain_id}: {chain.molecule_type}, length {chain.residue_count}"
            )
        if analysis.ligands:
            summary_lines.append("Ligands:")
            for ligand in analysis.ligands[:8]:
                summary_lines.append(
                    f"- {ligand.display_name} ({ligand.identifier}) in chain {ligand.chain_id}"
                )
        else:
            summary_lines.append("Ligands: none detected")

        try:
            review = self.screen.app.create_pdb_review_skill().review_summary(
                "\n".join(summary_lines)
            )
        except Exception:
            return analysis

        semantic_status = clean_text(review.get("semantic_status")) or "unknown"
        note = clean_text(review.get("note")) or ""
        return analysis.model_copy(
            update={
                "semantic_status": semantic_status,
                "semantic_note": note,
            }
        )

    def choose_chain(
        self,
        analysis: PdbAnalysisResult,
        user_sequence: str | None,
    ) -> PdbChainCandidate | None:
        if not analysis.nucleic_acid_chains:
            return None
        if len(analysis.nucleic_acid_chains) == 1:
            return analysis.nucleic_acid_chains[0]
        if user_sequence:
            matches = [
                chain
                for chain in analysis.nucleic_acid_chains
                if self.compare_sequence(user_sequence, chain.sequence) == "match"
            ]
            if len(matches) == 1:
                return matches[0]
        if analysis.recommended_chain_id:
            for chain in analysis.nucleic_acid_chains:
                if chain.chain_id == analysis.recommended_chain_id:
                    return chain
        return None

    def compare_sequence(self, user_sequence: str | None, pdb_sequence: str | None) -> str:
        return self.screen.app.pdb_analysis_adapter.compare_sequence(user_sequence, pdb_sequence)

    def apply_pdb_selection(self, chain_id: str | None, ligand_key: str | None) -> None:
        state = self.screen.app.current_state
        pdb_ctx = state.context.pdb_intake
        if not chain_id:
            self._activate_general_retry("A PDB chain was not selected.")
            return

        chain = next((item for item in pdb_ctx.chains if item.chain_id == chain_id), None)
        if chain is None:
            self._activate_general_retry("The selected PDB chain is no longer available.")
            return

        target_text = state.context.intake.target_input
        ligand = None
        if not target_text and ligand_key:
            ligand = next((item for item in pdb_ctx.ligands if item.key == ligand_key), None)
            target_text = ligand.display_name if ligand else None

        record_pdb_intake_context(
            state,
            selected_chain_id=chain.chain_id,
            selected_ligand_key=ligand.key if ligand else ligand_key,
            derived_sequence=chain.sequence,
            needs_user_selection=False,
        )

        self.finalize_pdb_import(
            analysis=PdbAnalysisResult(
                pdb_id=pdb_ctx.pdb_id or "unknown",
                artifact_path=pdb_ctx.artifact_path or "",
                nucleic_acid_chains=pdb_ctx.chains,
                ligands=pdb_ctx.ligands,
                recommended_chain_id=pdb_ctx.recommended_chain_id,
                recommended_ligand_key=pdb_ctx.recommended_ligand_key,
                semantic_status=pdb_ctx.semantic_validation_status,
                semantic_note=pdb_ctx.semantic_note or "",
            ),
            chain=chain,
            ligand=ligand,
            target_text=target_text,
            user_brief=state.context.intake.user_brief,
            modification_region=state.input_payload.get("modification_region"),
            analogs=state.input_payload.get("analogs", []),
            time_budget_hours=state.time_budget,
        )

    def finalize_pdb_import(
        self,
        *,
        analysis: PdbAnalysisResult,
        chain: PdbChainCandidate,
        ligand: PdbLigandCandidate | None,
        target_text: str | None,
        user_brief: str | None,
        modification_region: str | None,
        analogs: list[str],
        time_budget_hours: int | None,
    ) -> None:
        state = self.screen.app.current_state

        self.screen.app.call_from_thread(
            self.screen.add_tool_message,
            "\n".join(
                [
                    "**PDB Intake Agent**",
                    "",
                    f"- PDB: `{analysis.pdb_id}`",
                    f"- Selected chain: `{chain.chain_id}` ({chain.molecule_type}, {chain.residue_count} nt)",
                    f"- Derived sequence: `{chain.sequence}`",
                    (
                        f"- Ligand source: `{ligand.display_name}`"
                        if ligand
                        else f"- Ligand source: `{target_text or 'not detected'}`"
                    ),
                    (
                        f"- Semantic note: {analysis.semantic_note}"
                        if analysis.semantic_note
                        else "- Semantic note: no additional review note"
                    ),
                ]
            ),
            label="agent:pdb",
        )

        if not target_text:
            state.target_molecule = None
            state.input_payload["initial_sequence"] = chain.sequence
            state.input_payload.pop("target_molecule", None)
            record_intake_context(
                state,
                user_brief=user_brief,
                sequence=chain.sequence,
                target_text=None,
                modification_region=modification_region,
                analogs=analogs,
                time_budget_hours=time_budget_hours,
                phase="awaiting_missing_target",
                last_resolution_error="No target molecule was detected from the PDB import.",
            )
            self.screen.app.save_state()
            self.screen.app.call_from_thread(self.screen.advance_to_step, Step.INTAKE)
            return

        self._resolve_and_complete(
            sequence=chain.sequence,
            target_text=target_text,
            user_brief=user_brief,
            modification_region=modification_region,
            analogs=analogs,
            time_budget_hours=time_budget_hours,
            source_label=f"PDB `{analysis.pdb_id}` chain `{chain.chain_id}`",
        )

    def show_selection_panel(self) -> None:
        state = self.screen.app.current_state
        pdb_ctx = state.context.pdb_intake
        chain_choices = [
            (
                chain.chain_id,
                f"Chain {chain.chain_id}",
                f"{chain.molecule_type}, {chain.residue_count} nt, sequence {chain.sequence}",
            )
            for chain in pdb_ctx.chains
        ]
        ligand_choices = []
        if not state.context.intake.target_input and len(pdb_ctx.ligands) > 1:
            ligand_choices = [
                (
                    ligand.key,
                    ligand.display_name,
                    f"{ligand.identifier} in chain {ligand.chain_id}, residue {ligand.residue_number}",
                )
                for ligand in pdb_ctx.ligands
            ]
        self.screen.add_structured_widget(
            PdbSelectionPanel(
                chain_choices=chain_choices,
                ligand_choices=ligand_choices,
            )
        )
