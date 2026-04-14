from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, DataTable, Static

from aptgent.adapters.spatial_rank import SpatialRankAdapter
from aptgent.domain.models import SpatialRankResult


class SpatialRankScreen(Screen):
    """Rank candidates using spatial interaction rules matrix."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)

    def compose(self) -> ComposeResult:
        yield self.app.progress_bar
        yield self.app.status_panel

        with Vertical(id="content-area"):
            yield Static("Step 9: Spatial Interaction Rank", classes="title")
            yield Static("", id="rank-status")
            yield DataTable(id="rank-table")

        with Horizontal(id="action-bar"):
            yield Button("Run Ranking", id="btn-run", variant="primary")
            yield Button("Back", id="btn-back")
            yield Button("Continue", id="btn-continue", variant="success", disabled=True)

    def on_mount(self) -> None:
        table = self.query_one("#rank-table", DataTable)
        table.add_columns("Rank", "Candidate", "Spatial Score", "Detected Groups")

        state = self.app.current_state
        if state.spatial_ranks:
            self._populate_table()
            self.query_one("#btn-continue", Button).disabled = False
            self.query_one("#rank-status", Static).update("Ranking already completed.")

    def _populate_table(self) -> None:
        table = self.query_one("#rank-table", DataTable)
        table.clear()
        state = self.app.current_state
        sorted_ranks = sorted(state.spatial_ranks, key=lambda r: r.rank)
        for r in sorted_ranks:
            groups = ", ".join(r.detected_groups[:5])
            if len(r.detected_groups) > 5:
                groups += f" (+{len(r.detected_groups) - 5} more)"
            table.add_row(
                str(r.rank),
                r.candidate_id,
                f"{r.spatial_score:.4f}",
                groups or "-",
            )

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-run":
            await self._run_ranking()
        elif event.button.id == "btn-continue":
            self.app.advance_step()
        elif event.button.id == "btn-back":
            self.app.pop_screen()

    async def _run_ranking(self) -> None:
        state = self.app.current_state
        target = state.target_molecule
        status = self.query_one("#rank-status", Static)

        if not target:
            status.update("Target molecule missing.")
            status.add_class("error-text")
            return

        # Use docked candidates if available, otherwise all candidates
        if state.docking_results:
            docked_ids = {r.candidate_id for r in state.docking_results}
            candidates = [
                c for c in state.candidates if c.candidate_id in docked_ids
            ]
        else:
            candidates = state.candidates

        if not candidates:
            status.update("No candidates available.")
            return

        status.update(f"Running spatial ranking on {len(candidates)} candidates...")

        try:
            results: list[SpatialRankResult] = self.app.spatial_rank_adapter.rank_batch(
                candidates, target
            )
            state.spatial_ranks = results
            self.app.save_state()
            self._populate_table()
            status.update("Spatial ranking complete.")
            status.add_class("success-text")
            self.query_one("#btn-continue", Button).disabled = False
        except Exception as e:
            status.update(f"Ranking failed: {e}")
            status.add_class("error-text")
