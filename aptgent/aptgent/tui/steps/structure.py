from __future__ import annotations

from aptgent.domain.enums import Step
from aptgent.tui.steps.base import StepHandler
from aptgent.tui.steps.common import next_step
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
                    "**Secondary-structure source selection**",
                    "",
                    f"- Sequence length: **{len(seq)}**",
                    "- Strategy: check lookup adapter, then fall back to RNAfold.",
                ]
            )
        )
        self.run_worker(self._run_fold, activity="Folding secondary structure...")

    def _run_fold(self) -> None:
        state = self.screen.app.current_state
        seq = get_sequence(state) or ""
        try:
            lookup_result = self.screen.app.structure_lookup_adapter.lookup(seq)
            lookup_note = (
                lookup_result.note if lookup_result.status != "not_configured" else None
            )
            record_secondary_structure_context(
                state,
                lookup_status=lookup_result.status,
                query_sequence=seq,
                match_ids=[match.structure_id for match in lookup_result.matches],
                note=lookup_note,
            )
            if lookup_result.status == "found":
                self.screen.app.call_from_thread(
                    self.screen.add_tool_message,
                    "\n".join(
                        [
                            "**Solved-structure lookup**",
                            "",
                            f"- Matches: {', '.join(match.structure_id for match in lookup_result.matches)}",
                            "- Automatic fetch/derivation is not enabled yet in this workflow.",
                            "- Falling back to `RNAfold` for this run.",
                        ]
                    ),
                )
            elif lookup_note:
                self.screen.app.call_from_thread(
                    self.screen.add_tool_message,
                    "\n".join(
                        [
                            "**Solved-structure lookup**",
                            "",
                            f"- Status: `{lookup_result.status}`",
                            f"- Note: {lookup_note}",
                        ]
                    ),
                )

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
            state.secondary_structure = struct
            record_secondary_structure_context(
                state,
                source="rnafold",
                note="Secondary structure generated from RNAfold.",
            )
            self.screen.app.save_state()
            result_text = "\n".join(
                [
                    "### Secondary Structure Ready",
                    "",
                    f"- **Sequence**: `{struct.sequence}`",
                    f"- **Dot-bracket**: `{struct.dot_bracket}`",
                    f"- **MFE**: `{struct.mfe}` kcal/mol",
                    f"- **Source**: `{struct.features.get('source', 'unknown')}`",
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
