from __future__ import annotations

from aptgent.domain.enums import Step
from aptgent.tui.steps.base import StepHandler
from aptgent.tui.steps.common import next_step
from aptgent.workflow.context import get_sequence


class StructureHandler(StepHandler):
    def enter(self) -> None:
        state = self.screen.app.current_state
        seq = get_sequence(state) or ""
        if not seq:
            self.screen.add_system_message("Error: no sequence available.", "error-text")
            self.screen.set_input_enabled(True)
            return
        self.screen.add_system_message(f"Running RNAfold on: {seq}")
        self.run_worker(self._run_fold, activity="Folding secondary structure...")

    def _run_fold(self) -> None:
        state = self.screen.app.current_state
        seq = get_sequence(state) or ""
        try:
            struct = self.screen.app.rna_fold_adapter.fold(seq)
            state.secondary_structure = struct
            self.screen.app.save_state()
            result_text = (
                f"Sequence: {struct.sequence}\n"
                f"Dot-bracket: {struct.dot_bracket}\n"
                f"MFE: {struct.mfe} kcal/mol"
            )
            self.screen.app.call_from_thread(self.screen.add_system_message, result_text)
            ns = next_step(Step.SECONDARY_STRUCTURE)
            if ns:
                self.screen.app.call_from_thread(self.screen.advance_to_step, ns)
        except Exception as exc:
            self.screen.app.call_from_thread(
                self.screen.add_system_message, f"RNAfold error: {exc}", "error-text"
            )
            self.screen.app.call_from_thread(self.screen.set_input_enabled, True)
