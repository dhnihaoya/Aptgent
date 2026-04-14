from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, DataTable, ProgressBar, Static

class DockingRunScreen(Screen):
    """Run molecular docking on top-k candidates via AutoDock Vina."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)

    def compose(self) -> ComposeResult:
        yield self.app.progress_bar
        yield self.app.status_panel

        with Vertical(id="content-area"):
            yield Static("Step 8: Docking Run", classes="title")
            yield Static("", id="dock-run-status")
            yield ProgressBar(total=100, id="dock-progress")
            yield DataTable(id="dock-table")

        with Horizontal(id="action-bar"):
            yield Button("Run Docking", id="btn-run", variant="primary")
            yield Button("Back", id="btn-back")
            yield Button("Continue", id="btn-continue", variant="success", disabled=True)

    def on_mount(self) -> None:
        self.query_one("#dock-progress", ProgressBar).update(progress=0)
        table = self.query_one("#dock-table", DataTable)
        table.add_columns("Candidate", "Docking Score", "Status")

        state = self.app.current_state
        if state.docking_results:
            self._populate_table()
            self.query_one("#btn-continue", Button).disabled = False
            self.query_one("#dock-run-status", Static).update("Docking already completed.")

    def _populate_table(self) -> None:
        table = self.query_one("#dock-table", DataTable)
        table.clear()
        state = self.app.current_state
        sorted_results = sorted(
            state.docking_results,
            key=lambda r: r.docking_score or 0.0,
        )
        for r in sorted_results:
            score_str = f"{r.docking_score:.3f}" if r.docking_score is not None else "N/A"
            table.add_row(r.candidate_id, score_str, r.status)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-run":
            await self._run_docking()
        elif event.button.id == "btn-continue":
            self.app.advance_step()
        elif event.button.id == "btn-back":
            self.app.pop_screen()

    async def _run_docking(self) -> None:
        state = self.app.current_state
        target = state.target_molecule
        status = self.query_one("#dock-run-status", Static)
        progress = self.query_one("#dock-progress", ProgressBar)

        if not target or not target.smiles:
            status.update("Target molecule missing.")
            status.add_class("error-text")
            return

        plan = state.docking_plan
        if not plan or plan.recommended_top_k <= 0:
            status.update("No docking plan set. Please go back and configure.")
            status.add_class("error-text")
            return

        if not plan.receptor_path:
            status.update("Receptor PDBQT path not set. Please go back and provide it.")
            status.add_class("error-text")
            return

        if not plan.grid_center or not plan.grid_size:
            status.update("Grid box parameters not set. Please go back and configure.")
            status.add_class("error-text")
            return

        receptor_path = Path(plan.receptor_path)
        if not receptor_path.exists():
            status.update(f"Receptor file not found: {plan.receptor_path}")
            status.add_class("error-text")
            return

        # Select top-k candidates (by primary scoring rank)
        ens_preds = [p for p in state.predictions if p.model_name == "ensemble"]
        sorted_preds = sorted(ens_preds, key=lambda x: x.probability or 0.0, reverse=True)
        top_k = plan.recommended_top_k
        top_cand_ids = {p.candidate_id for p in sorted_preds[:top_k]}
        top_candidates = [
            c for c in state.candidates if c.candidate_id in top_cand_ids
        ]

        if not top_candidates:
            status.update("No candidates selected for docking.")
            return

        status.update(f"Running Vina docking on {len(top_candidates)} candidates...")
        progress.update(total=len(top_candidates), progress=0)

        try:
            # Work directory under the run's artifacts
            work_dir = Path(state.run_id) / "docking" if not Path(state.run_id).is_absolute() else Path(state.run_id) / "docking"

            results = self.app.vina_adapter.run_batch(
                candidates=top_candidates,
                target=target,
                receptor_pdbqt=receptor_path,
                center=plan.grid_center,
                size=plan.grid_size,
                work_dir=work_dir,
            )
            state.docking_results = results
            self.app.save_state()
            self._populate_table()
            progress.update(progress=len(top_candidates))
            status.update(f"Docking complete. {len(results)} results obtained.")
            status.add_class("success-text")
            self.query_one("#btn-continue", Button).disabled = False
        except Exception as e:
            status.update(f"Docking failed: {e}")
            status.add_class("error-text")
