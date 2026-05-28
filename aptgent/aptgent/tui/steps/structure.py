from __future__ import annotations

from aptgent.domain.enums import Step
from aptgent.tui.steps.base import StepHandler
from aptgent.tui.steps.common import next_primary_step, section_heading
from aptgent.workflow.context import get_sequence, record_secondary_structure_context


class StructureHandler(StepHandler):

    def _has_pdb_context(self) -> bool:
        pdb_ctx = self.screen.app.current_state.context.pdb_intake
        return bool(pdb_ctx.artifact_path and pdb_ctx.selected_chain_id)

    def enter(self) -> None:
        state = self.screen.app.current_state
        seq = get_sequence(state) or ""
        if not seq:
            self.screen.add_system_message("Error: no sequence available.", "error-text")
            self.screen.set_input_enabled(True)
            return

        if self._has_pdb_context():
            pdb_ctx = state.context.pdb_intake
            self.screen.add_tool_message(
                "\n".join(
                    [
                        "**Secondary-structure prediction**",
                        "",
                        f"- Sequence length: **{len(seq)}**",
                        f"- Method: PDB-derived (PDB `{pdb_ctx.pdb_id}`, chain `{pdb_ctx.selected_chain_id}`)",
                    ]
                )
            )
            self.run_worker(self._run_pdb_derive, activity="Deriving structure from PDB...")
        else:
            self.screen.add_tool_message(
                "\n".join(
                    [
                        "**Secondary-structure prediction**",
                        "",
                        f"- Sequence length: **{len(seq)}**",
                        "- Method: RNAfold",
                    ]
                )
            )
            self.run_worker(self._run_rnafold, activity="Running RNAfold...")

    def _run_pdb_derive(self) -> None:
        state = self.screen.app.current_state
        pdb_ctx = state.context.pdb_intake
        try:
            struct = self.screen.app.pdb_analysis_adapter.derive_secondary_structure(
                pdb_id=pdb_ctx.pdb_id,
                artifact_path=pdb_ctx.artifact_path,
                chain_id=pdb_ctx.selected_chain_id,
            )
            struct.features.setdefault("source", "pdb")
            self._store_secondary_structure(
                struct,
                source="pdb",
                note="Using PDB-derived secondary structure.",
            )
        except Exception as exc:
            self._threadsafe(
                self.screen.add_tool_message,
                f"PDB derivation failed ({exc}), falling back to RNAfold.",
            )
            self._run_rnafold()

    def _run_rnafold(self) -> None:
        state = self.screen.app.current_state
        seq = get_sequence(state) or ""
        try:
            self._threadsafe(
                self.screen.add_tool_message,
                "\n".join(
                    [
                        "**Running RNAfold**",
                        "",
                        f"- Sequence: `{seq}`",
                    ]
                ),
            )
            struct = self.screen.app.rna_fold_adapter.fold(seq)
            struct.features.setdefault("source", "rnafold")
            self._store_secondary_structure(
                struct,
                source="rnafold",
                note="Secondary structure generated from RNAfold.",
            )
        except Exception as exc:
            record_secondary_structure_context(
                state,
                lookup_status="failed",
                source="rnafold",
                note=str(exc),
            )
            self._threadsafe(
                self.screen.add_system_message, f"RNAfold error: {exc}", "error-text"
            )
            self._enable_input()

    def _store_secondary_structure(self, struct, *, source: str, note: str) -> None:
        state = self.screen.app.current_state
        pdb_ctx = state.context.pdb_intake
        state.secondary_structure = struct
        record_secondary_structure_context(
            state,
            source=source,
            query_sequence=struct.sequence,
            downloaded_artifact_path=pdb_ctx.artifact_path,
            note=note,
        )
        self.screen.app.save_state()
        if source == "pdb":
            selection_label = "Using PDB-derived secondary structure."
        else:
            selection_label = "Using RNAfold-generated secondary structure."
        result_text = "\n".join(
            [
                section_heading("Secondary Structure Ready"),
                "",
                f"- **Sequence**: `{struct.sequence}`",
                f"- **Dot-bracket**: `{struct.dot_bracket}`",
                f"- **MFE**: `{struct.mfe}` kcal/mol",
                f"- **Selection**: {selection_label}",
                f"- **Source**: `{struct.features.get('source', source)}`",
            ]
        )
        self._threadsafe(
            lambda: self.screen.add_system_message(
                result_text,
                extra_class="",
                markdown=True,
            )
        )
        ns = next_primary_step(Step.SECONDARY_STRUCTURE)
        if ns:
            self._threadsafe(self.screen.advance_to_step, ns)
