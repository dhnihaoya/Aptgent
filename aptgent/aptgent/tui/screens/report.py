from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, DataTable, Static

from aptgent.domain.models import FinalRecommendation
from aptgent.llm.skills import ReportSkill


class ReportScreen(Screen):
    """Final report with ranked recommendations including Phase 2 data."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.skill = ReportSkill()

    def compose(self) -> ComposeResult:
        yield self.app.progress_bar
        yield self.app.status_panel

        with Vertical(id="content-area"):
            yield Static("Final Report", classes="title")
            yield Static("", id="report-summary", classes="info-text")
            yield DataTable(id="report-table")

        with Horizontal(id="action-bar"):
            yield Button("Export JSON", id="btn-export", variant="primary")
            yield Button("Finish", id="btn-finish", variant="success")

    def on_mount(self) -> None:
        self._build_report()

    def _build_report(self) -> None:
        state = self.app.current_state
        table = self.query_one("#report-table", DataTable)
        table.add_columns(
            "Priority", "Candidate", "Edit Ratio", "Primary Score",
            "Specificity", "Docking Score", "Spatial Rank", "Sequence"
        )

        # Build lookup maps for Phase 2 data
        spec_map = {
            r.candidate_id: r for r in state.specificity_results
        }
        dock_map = {
            r.candidate_id: r for r in state.docking_results
        }
        spatial_map = {
            r.candidate_id: r for r in state.spatial_ranks
        }

        # Start from primary scoring ensemble results
        ens_preds = [p for p in state.predictions if p.model_name == "ensemble"]
        sorted_preds = sorted(ens_preds, key=lambda x: x.probability or 0.0, reverse=True)

        # Filter out removed candidates (if specificity filter was run)
        kept_ids: set[str] | None = None
        if state.specificity_results:
            kept_ids = {
                r.candidate_id for r in state.specificity_results
                if r.status in ("kept", "skipped")
            }

        recommendations: list[FinalRecommendation] = []
        for rank, p in enumerate(sorted_preds, start=1):
            cand_id = p.candidate_id

            # Skip removed candidates
            if kept_ids is not None and cand_id not in kept_ids:
                continue

            cand = next((c for c in state.candidates if c.candidate_id == cand_id), None)
            edit_ratio = f"{cand.edit_ratio:.2f}" if cand else ""
            seq_short = (cand.sequence[:30] + "...") if cand else ""

            # Phase 2 data
            spec = spec_map.get(cand_id)
            spec_status = spec.status if spec else "pending"

            dock = dock_map.get(cand_id)
            dock_score = f"{dock.docking_score:.3f}" if dock and dock.docking_score is not None else "-"

            spatial = spatial_map.get(cand_id)
            spatial_rank = str(spatial.rank) if spatial else "-"

            # Adjust rank based on spatial ranking if available
            final_priority = spatial.rank if spatial and spatial.rank > 0 else rank

            rec = FinalRecommendation(
                candidate_id=cand_id,
                primary_score=p.probability or 0.0,
                specificity_status=spec_status,
                docking_score=dock.docking_score if dock else None,
                spatial_rank=spatial.rank if spatial else None,
                final_priority=final_priority,
                explanation="",
            )
            recommendations.append(rec)
            table.add_row(
                str(final_priority),
                cand_id,
                edit_ratio,
                f"{p.probability:.4f}",
                spec_status,
                dock_score,
                spatial_rank,
                seq_short,
            )

        state.recommendations = recommendations
        self.app.save_state()

        # Optional LLM summary (non-blocking best-effort)
        try:
            rec_dicts = [r.model_dump() for r in recommendations[:10]]
            summary = self.skill.summarize(rec_dicts)
            self.query_one("#report-summary", Static).update(summary.get("summary", ""))
        except Exception:
            self.query_one("#report-summary", Static).update(
                "Report generated from deterministic scoring results."
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-export":
            self._export()
        elif event.button.id == "btn-finish":
            self.app.engine.complete(self.app.current_state)
            self.app.exit(message="Workflow completed.")

    def _export(self) -> None:
        state = self.app.current_state
        data = {
            "run_id": state.run_id,
            "recommendations": [r.model_dump() for r in state.recommendations],
            "specificity_results": [r.model_dump() for r in state.specificity_results],
            "docking_results": [r.model_dump() for r in state.docking_results],
            "spatial_ranks": [r.model_dump() for r in state.spatial_ranks],
        }
        path = self.app.persistence.write_artifact(state.run_id, "final_report.json", data)
        self.query_one("#report-summary", Static).update(f"Exported to {path}")
