from __future__ import annotations

from aptgent.domain.enums import Step
from aptgent.tui.steps.base import StepHandler
from aptgent.tui.steps.common import next_step, section_heading
from aptgent.workflow.context import get_sequence, record_secondary_structure_context


class StructureHandler(StepHandler):
    def enter(self) -> None:
        state = self.screen.app.current_state
        seq = get_sequence(state) or ""
        if not seq:
            self.screen.add_system_message("Error: no sequence available.", "error-text")
            self.screen.set_input_enabled(True)
            return
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

    def _run_rnafold(self) -> None:
        state = self.screen.app.current_state
        seq = get_sequence(state) or ""
        try:
            self.screen.app.call_from_thread(
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
            self.screen.app.call_from_thread(
                self.screen.add_system_message, f"RNAfold error: {exc}", "error-text"
            )
            self.screen.app.call_from_thread(self.screen.set_input_enabled, True)

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
        result_text = "\n".join(
            [
                section_heading("Secondary Structure Ready"),
                "",
                f"- **Sequence**: `{struct.sequence}`",
                f"- **Dot-bracket**: `{struct.dot_bracket}`",
                f"- **MFE**: `{struct.mfe}` kcal/mol",
                "- **Selection**: Using RNAfold-generated secondary structure.",
                f"- **Source**: `{struct.features.get('source', source)}`",
            ]
        )
        self.screen.app.call_from_thread(
            lambda: self.screen.add_system_message(
                result_text,
                extra_class="",
                markdown=True,
            )
        )
        ns = next_step(Step.SECONDARY_STRUCTURE)
        if ns:
            self.screen.app.call_from_thread(self.screen.advance_to_step, ns)
