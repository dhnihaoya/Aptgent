from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Label, Static

from aptgent.domain.models import SecondaryStructure


class StructureScreen(Screen):
    """Display RNA secondary structure from RNAfold."""

    def compose(self) -> ComposeResult:
        yield self.app.progress_bar
        yield self.app.status_panel

        with Vertical(id="content-area"):
            yield Static("Step 2: Secondary Structure", classes="title")
            yield Static("Running RNAfold...", id="structure-output")

        with Horizontal(id="action-bar"):
            yield Button("Back", id="btn-back")
            yield Button("Continue", id="btn-continue", variant="primary")

    def on_mount(self) -> None:
        self._run_fold()

    def _run_fold(self) -> None:
        state = self.app.current_state
        seq = state.input_payload.get("initial_sequence", "")
        if not seq:
            out = self.query_one("#structure-output", Static)
            out.update("Error: no sequence available.")
            out.add_class("error-text")
            return

        try:
            struct = self.app.rna_fold_adapter.fold(seq)
            state.secondary_structure = struct
            self.app.save_state()
            self.query_one("#structure-output", Static).update(
                f"Sequence:\n{struct.sequence}\n\n"
                f"Dot-bracket:\n{struct.dot_bracket}\n\n"
                f"MFE: {struct.mfe} kcal/mol"
            )
        except FileNotFoundError as e:
            out = self.query_one("#structure-output", Static)
            out.update(
                f"RNAfold not found: {e}\n\n"
                "Please install ViennaRNA and ensure RNAfold is in your PATH, "
                "then click Continue to retry or Back to return."
            )
            out.add_class("error-text")
        except Exception as e:
            out = self.query_one("#structure-output", Static)
            out.update(f"RNAfold error: {e}")
            out.add_class("error-text")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-continue":
            if self.app.current_state.secondary_structure is None:
                self._run_fold()
                if self.app.current_state.secondary_structure is not None:
                    self.app.advance_step()
            else:
                self.app.advance_step()
        elif event.button.id == "btn-back":
            self.app.pop_screen()
