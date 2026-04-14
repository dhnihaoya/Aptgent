from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, DataTable, Input, Static

from aptgent.domain.models import SpecificityResult, TargetMolecule
from aptgent.llm.skills import AnalogSuggestionSkill


class SpecificityFilterScreen(Screen):
    """Run cross-prediction against analogs to filter non-specific candidates."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.skill = AnalogSuggestionSkill()

    def compose(self) -> ComposeResult:
        yield self.app.progress_bar
        yield self.app.status_panel

        with Vertical(id="content-area"):
            yield Static("Step 6: Specificity Filter", classes="title")
            yield Static(
                "Enter analog molecules (comma-separated names or SMILES) or let the LLM suggest them.",
                classes="info-text",
            )
            yield Input(id="analog-input", placeholder="e.g. adenine, hypoxanthine")
            yield Static("", id="filter-status")
            yield DataTable(id="filter-table")

        with Horizontal(id="action-bar"):
            yield Button("Suggest Analogs", id="btn-suggest", variant="primary")
            yield Button("Run Filter", id="btn-run", variant="warning")
            yield Button("Skip", id="btn-skip")
            yield Button("Back", id="btn-back")
            yield Button("Continue", id="btn-continue", variant="success", disabled=True)

    def on_mount(self) -> None:
        state = self.app.current_state
        if state.analogs:
            names = ", ".join(a.input_text for a in state.analogs)
            self.query_one("#analog-input", Input).value = names
        if state.specificity_results:
            self._populate_table()
            self.query_one("#btn-continue", Button).disabled = False
            self.query_one("#filter-status", Static).update("Filter already completed.")

    def _populate_table(self) -> None:
        table = self.query_one("#filter-table", DataTable)
        table.clear()
        table.add_columns("Candidate", "Primary Score", "Status", "Failed Analogs")

        state = self.app.current_state
        primary_preds = {
            p.candidate_id: p
            for p in state.predictions
            if p.model_name == "ensemble"
        }
        for res in state.specificity_results:
            cand = next(
                (c for c in state.candidates if c.candidate_id == res.candidate_id), None
            )
            if not cand:
                continue
            primary = primary_preds.get(res.candidate_id)
            score = f"{primary.probability:.4f}" if primary else "N/A"
            failed = ", ".join(res.failed_analogs) if res.failed_analogs else "-"
            table.add_row(res.candidate_id, score, res.status, failed)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "btn-suggest":
            await self._suggest_analogs()
        elif btn_id == "btn-run":
            await self._run_filter()
        elif btn_id == "btn-skip":
            self._skip_filter()
        elif btn_id == "btn-continue":
            self.app.advance_step()
        elif btn_id == "btn-back":
            self.app.pop_screen()

    async def _suggest_analogs(self) -> None:
        state = self.app.current_state
        target = state.target_molecule
        if not target:
            self.query_one("#filter-status", Static).update(
                "No target molecule available."
            )
            return

        self.query_one("#filter-status", Static).update("Asking LLM for analog suggestions...")
        try:
            result = self.skill.suggest(target)
            analogs = result.get("analogs", [])
            names = ", ".join(a.get("name", "") for a in analogs if a.get("name"))
            self.query_one("#analog-input", Input).value = names
            self.query_one("#filter-status", Static).update(
                f"Suggested {len(analogs)} analogs."
            )
        except Exception as e:
            self.query_one("#filter-status", Static).update(f"Suggestion failed: {e}")

    async def _run_filter(self) -> None:
        state = self.app.current_state
        candidates = state.candidates
        target = state.target_molecule

        status = self.query_one("#filter-status", Static)
        if not candidates:
            status.update("No candidates available.")
            return
        if not target or not target.smiles:
            status.update("Target molecule missing.")
            return

        # Parse analogs
        raw_text = self.query_one("#analog-input", Input).value.strip()
        analogs: list[TargetMolecule] = []
        if raw_text:
            for part in raw_text.split(","):
                part = part.strip()
                if not part:
                    continue
                resolved = self.app.molecule_resolver.resolve(part)
                if resolved.resolution_status == "resolved":
                    analogs.append(resolved)
                else:
                    analogs.append(TargetMolecule(input_text=part, resolution_status="failed"))

        state.analogs = analogs
        self.app.save_state()

        if not analogs:
            status.update("No analogs provided. Nothing to filter.")
            return

        status.update(f"Running cross-prediction on {len(candidates)} candidates × {len(analogs)} analogs...")

        try:
            results_by_target = self.app.prediction_adapter.predict_batch_for_targets(
                candidates, [target] + analogs
            )
        except Exception as e:
            status.update(f"Prediction failed: {e}")
            return

        primary_results = results_by_target.get(target.smiles, [])
        specificity_results: list[SpecificityResult] = []
        kept_count = 0

        for cand in candidates:
            cand_id = cand.candidate_id or ""
            failed: list[str] = []
            for analog in analogs:
                if not analog.smiles:
                    continue
                analog_preds = results_by_target.get(analog.smiles, [])
                ap = next((p for p in analog_preds if p.candidate_id == cand_id), None)
                if ap and ap.label == 1:
                    failed.append(analog.input_text)

            status_str = "removed" if failed else "kept"
            if not failed:
                kept_count += 1

            specificity_results.append(
                SpecificityResult(
                    candidate_id=cand_id,
                    status=status_str,
                    failed_analogs=failed,
                    raw_outputs={"analog_count": len(analogs)},
                )
            )

        state.specificity_results = specificity_results
        # Keep primary predictions only for reference (already stored in state.predictions)
        self.app.save_state()
        self._populate_table()
        status.update(f"Filter complete. {kept_count}/{len(candidates)} candidates kept.")
        self.query_one("#btn-continue", Button).disabled = False

    def _skip_filter(self) -> None:
        state = self.app.current_state
        state.specificity_results = [
            SpecificityResult(candidate_id=c.candidate_id or "", status="skipped")
            for c in state.candidates
        ]
        self.app.save_state()
        self._populate_table()
        self.query_one("#filter-status", Static).update("Filter skipped.")
        self.query_one("#btn-continue", Button).disabled = False
