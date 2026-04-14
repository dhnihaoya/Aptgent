from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, DataTable, Label, ProgressBar, Static

from aptgent.domain.enums import Status
from aptgent.domain.models import PredictionResult


class ScoringScreen(Screen):
    """Run prediction model on candidates and display results."""

    def compose(self) -> ComposeResult:
        yield self.app.progress_bar
        yield self.app.status_panel

        with Vertical(id="content-area"):
            yield Static("Step 5: Primary Scoring", classes="title")
            yield Static("", id="score-status")
            yield ProgressBar(total=100, id="score-progress")
            yield DataTable(id="score-table")

        with Horizontal(id="action-bar"):
            yield Button("Run Scoring", id="btn-run", variant="primary")
            yield Button("Back", id="btn-back")
            yield Button("Continue", id="btn-continue", variant="success", disabled=True)

    def on_mount(self) -> None:
        self.query_one("#score-progress", ProgressBar).update(progress=0)
        table = self.query_one("#score-table", DataTable)
        table.add_columns("Candidate", "Label", "Probability", "Sequence")
        state = self.app.current_state
        if state.predictions:
            self._populate_table()
            self.query_one("#btn-continue", Button).disabled = False
            self.query_one("#score-status", Static).update("Scoring already completed.")

    def _populate_table(self) -> None:
        table = self.query_one("#score-table", DataTable)
        table.clear()
        ens_preds = [p for p in self.app.current_state.predictions if p.model_name == "ensemble"]
        for p in sorted(ens_preds, key=lambda x: x.probability or 0.0, reverse=True):
            cand = next(
                (c for c in self.app.current_state.candidates if c.candidate_id == p.candidate_id),
                None,
            )
            seq = cand.sequence[:40] + "..." if cand else ""
            table.add_row(p.candidate_id, str(p.label), f"{p.probability:.4f}", seq)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-run":
            await self._run_scoring()
        elif event.button.id == "btn-continue":
            self.app.advance_step()
        elif event.button.id == "btn-back":
            self.app.pop_screen()

    async def _run_scoring(self) -> None:
        state = self.app.current_state
        candidates = state.candidates
        target = state.target_molecule

        status = self.query_one("#score-status", Static)
        progress = self.query_one("#score-progress", ProgressBar)

        if not candidates:
            status.update("No candidates available.")
            status.add_class("error-text")
            return

        if target is None or target.smiles is None:
            status.update("Target molecule missing. Please go back and provide it.")
            status.add_class("error-text")
            return

        status.update(f"Running ensemble prediction on {len(candidates)} candidates...")
        progress.update(total=len(candidates), progress=0)

        try:
            # Batch scoring via adapter
            results = self.app.prediction_adapter.predict_batch(candidates, target)
            state.predictions = results
            self.app.save_state()
            self._populate_table()
            progress.update(progress=len(candidates))
            status.update("Scoring complete.")
            status.add_class("success-text")
            self.query_one("#btn-continue", Button).disabled = False
        except Exception as e:
            status.update(f"Scoring failed: {e}")
            status.add_class("error-text")
