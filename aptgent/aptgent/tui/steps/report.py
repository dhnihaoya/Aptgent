from __future__ import annotations

from aptgent.domain.models import FinalRecommendation
from aptgent.llm.skills import ReportSkill
from aptgent.tui.steps.base import StepHandler
from aptgent.tui.steps.common import run_llm_interaction, validate_report_summary


class ReportHandler(StepHandler):
    def enter(self) -> None:
        self.run_worker(self._build_report, activity="Compiling final report...")

    def _build_report(self) -> None:
        state = self.screen.app.current_state

        spec_map = {result.candidate_id: result for result in state.specificity_results}
        dock_map = {result.candidate_id: result for result in state.docking_results}
        spatial_map = {result.candidate_id: result for result in state.spatial_ranks}

        ens_preds = [pred for pred in state.predictions if pred.model_name == "ensemble"]
        sorted_preds = sorted(
            ens_preds, key=lambda item: item.probability or 0.0, reverse=True
        )

        kept_ids: set[str] | None = None
        if state.specificity_results:
            kept_ids = {
                result.candidate_id
                for result in state.specificity_results
                if result.status in ("kept", "skipped")
            }

        recommendations: list[FinalRecommendation] = []
        lines = ["=== FINAL REPORT ==="]
        for rank, pred in enumerate(sorted_preds, start=1):
            cand_id = pred.candidate_id
            if kept_ids is not None and cand_id not in kept_ids:
                continue

            candidate = next(
                (item for item in state.candidates if item.candidate_id == cand_id),
                None,
            )

            spec = spec_map.get(cand_id)
            spec_status = spec.status if spec else "pending"

            dock = dock_map.get(cand_id)
            dock_score = f"{dock.docking_score:.3f}" if dock and dock.docking_score is not None else "-"

            spatial = spatial_map.get(cand_id)
            spatial_rank = str(spatial.rank) if spatial else "-"
            final_priority = spatial.rank if spatial and spatial.rank > 0 else rank

            seq_short = (candidate.sequence[:30] + "...") if candidate else ""

            rec = FinalRecommendation(
                candidate_id=cand_id,
                primary_score=pred.probability or 0.0,
                specificity_status=spec_status,
                docking_score=dock.docking_score if dock else None,
                spatial_rank=spatial.rank if spatial else None,
                final_priority=final_priority,
            )
            recommendations.append(rec)
            lines.append(
                f"  #{final_priority} {cand_id} | "
                f"Score={pred.probability:.4f} | Spec={spec_status} | "
                f"Dock={dock_score} | Spatial=#{spatial_rank}\n"
                f"         {seq_short}"
            )

        state.recommendations = recommendations
        self.screen.app.save_state()

        try:
            skill = ReportSkill()
            rec_dicts = [recommendation.model_dump() for recommendation in recommendations[:10]]
            summary_result = run_llm_interaction(
                self.screen,
                display_stream=lambda: skill.explain_summarize_stream(rec_dicts),
                structured_call=lambda: validate_report_summary(skill.summarize(rec_dicts)),
            )
            summary = summary_result.get("summary", "")
            if summary:
                lines.append(f"\nSummary: {summary}")
        except Exception:
            lines.append("\n(Report generated from deterministic scoring results.)")

        lines.append("\nType 'export' to save, 'finish' to exit.")

        self.screen.app.call_from_thread(
            self.screen.add_system_message, "\n".join(lines)
        )
        self.screen.app.call_from_thread(self.screen.set_input_enabled, True)
        self.screen.app.call_from_thread(
            self.screen.set_input_placeholder, "Type 'export' or 'finish'"
        )

    def handle_user_input(self, text: str) -> None:
        text_lower = text.strip().lower()
        if text_lower == "export":
            self._export()
        elif text_lower == "finish":
            self.screen.app.engine.complete(self.screen.app.current_state)
            self.screen.app.exit(message="Workflow completed.")

    def _export(self) -> None:
        state = self.screen.app.current_state
        data = {
            "run_id": state.run_id,
            "recommendations": [result.model_dump() for result in state.recommendations],
            "specificity_results": [result.model_dump() for result in state.specificity_results],
            "docking_results": [result.model_dump() for result in state.docking_results],
            "spatial_ranks": [result.model_dump() for result in state.spatial_ranks],
        }
        path = self.screen.app.persistence.write_artifact(
            state.run_id, "final_report.json", data
        )
        self.screen.add_system_message(f"Report exported to {path}")
        self.screen.set_input_placeholder("Type 'finish' to exit")
