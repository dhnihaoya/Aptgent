from __future__ import annotations

from collections import Counter
from typing import Any

from aptgent.domain.models import FinalRecommendation
from aptgent.llm.skills import ReportSkill
from aptgent.tui.steps.base import StepHandler


def _candidate_id(candidate: Any, fallback_index: int) -> str:
    return candidate.candidate_id or f"cand_{fallback_index}"


def _prediction_maps(state: Any) -> tuple[dict[str, Any], list[Any]]:
    ensemble = [pred for pred in state.predictions if pred.model_name == "ensemble"]
    by_id = {pred.candidate_id: pred for pred in ensemble}
    sorted_predictions = sorted(
        ensemble,
        key=lambda item: item.probability if item.probability is not None else item.score,
        reverse=True,
    )
    return by_id, sorted_predictions


def _status_counts(results: list[Any]) -> dict[str, int]:
    return dict(Counter(result.status for result in results))


def build_report_context(state: Any) -> dict[str, Any]:
    """Build deterministic report facts before the LLM writes prose."""
    prediction_by_id, sorted_predictions = _prediction_maps(state)
    candidate_by_id = {
        _candidate_id(candidate, index): candidate
        for index, candidate in enumerate(state.candidates)
    }
    specificity_by_id = {
        result.candidate_id: result for result in state.specificity_results
    }
    docking_by_id = {result.candidate_id: result for result in state.docking_results}
    spatial_by_id = {result.candidate_id: result for result in state.spatial_ranks}
    docked_ids = set(docking_by_id)

    if state.spatial_ranks:
        ordered_docked_ids = [
            result.candidate_id
            for result in sorted(state.spatial_ranks, key=lambda item: item.rank or 999999)
            if result.candidate_id in docked_ids
        ]
    else:
        ordered_docked_ids = [
            result.candidate_id
            for result in sorted(
                state.docking_results,
                key=lambda item: (
                    item.docking_score is None,
                    item.docking_score if item.docking_score is not None else 0.0,
                ),
            )
        ]

    docking_candidates: list[dict[str, Any]] = []
    recommendations: list[FinalRecommendation] = []
    for priority, cand_id in enumerate(ordered_docked_ids, start=1):
        candidate = candidate_by_id.get(cand_id)
        prediction = prediction_by_id.get(cand_id)
        specificity = specificity_by_id.get(cand_id)
        docking = docking_by_id.get(cand_id)
        spatial = spatial_by_id.get(cand_id)

        primary_score = (
            prediction.probability
            if prediction and prediction.probability is not None
            else prediction.score if prediction else 0.0
        )
        specificity_status = specificity.status if specificity else "pending"
        final_priority = spatial.rank if spatial and spatial.rank > 0 else priority
        recommendations.append(
            FinalRecommendation(
                candidate_id=cand_id,
                primary_score=primary_score,
                specificity_status=specificity_status,
                docking_score=docking.docking_score if docking else None,
                spatial_rank=spatial.rank if spatial else None,
                final_priority=final_priority,
            )
        )
        docking_candidates.append(
            {
                "candidate_id": cand_id,
                "final_priority": final_priority,
                "sequence": candidate.sequence if candidate else "",
                "mutations": [
                    mutation.model_dump()
                    for mutation in (candidate.mutations if candidate else [])
                ],
                "edit_ratio": candidate.edit_ratio if candidate else None,
                "primary_score": primary_score,
                "primary_label": prediction.label if prediction else None,
                "specificity_status": specificity_status,
                "failed_analogs": specificity.failed_analogs if specificity else [],
                "docking_score": docking.docking_score if docking else None,
                "docking_status": docking.status if docking else "pending",
                "spatial_rank": spatial.rank if spatial else None,
                "spatial_score": spatial.spatial_score if spatial else None,
                "detected_groups": spatial.detected_groups if spatial else [],
            }
        )

    non_docked_predictions = [
        pred for pred in sorted_predictions if pred.candidate_id not in docked_ids
    ]
    non_docked_specificity = [
        result
        for result in state.specificity_results
        if result.candidate_id not in docked_ids
    ]
    probabilities = [
        pred.probability if pred.probability is not None else pred.score
        for pred in non_docked_predictions
    ]
    kept_non_docked = [
        result
        for result in non_docked_specificity
        if result.status in {"kept", "skipped"}
    ]
    removed_non_docked = [
        result for result in non_docked_specificity if result.status == "removed"
    ]

    return {
        "run_id": state.run_id,
        "target": {
            "input_text": state.target_molecule.input_text if state.target_molecule else "",
            "resolved_name": state.target_molecule.resolved_name if state.target_molecule else "",
            "smiles": state.target_molecule.smiles if state.target_molecule else "",
        },
        "docking_candidates": docking_candidates,
        "screening_overview": {
            "total_candidate_count": len(state.candidates),
            "ensemble_prediction_count": len(sorted_predictions),
            "docked_candidate_count": len(docking_candidates),
            "non_docked_candidate_count": len(non_docked_predictions),
            "non_docked_score_min": min(probabilities) if probabilities else None,
            "non_docked_score_max": max(probabilities) if probabilities else None,
            "non_docked_positive_count": sum(1 for pred in non_docked_predictions if pred.label == 1),
            "specificity_status_counts": _status_counts(non_docked_specificity),
            "kept_non_docked_count": len(kept_non_docked),
            "removed_non_docked_count": len(removed_non_docked),
        },
        "artifacts": {
            "sequences_export_dir": state.context.docking_recommendation.sequences_export_dir,
            "structures_dir": state.context.docking_recommendation.structures_dir,
        },
    }


def _format_score(value: Any) -> str:
    return f"{value:.4f}" if isinstance(value, (int, float)) else "n/a"


def format_deterministic_report_markdown(context: dict[str, Any]) -> str:
    target = context.get("target", {})
    overview = context.get("screening_overview", {})
    candidates = context.get("docking_candidates", [])
    target_name = target.get("resolved_name") or target.get("input_text") or "target"

    lines = [
        "# Final Report",
        "",
        f"Target: **{target_name}**",
        "",
        "## Docking Candidates for Documentation",
    ]
    if candidates:
        for candidate in candidates:
            lines.extend(
                [
                    "",
                    f"### #{candidate['final_priority']} {candidate['candidate_id']}",
                    "",
                    f"- Sequence: `{candidate['sequence']}`",
                    f"- Primary prediction score: **{_format_score(candidate['primary_score'])}**",
                    f"- Specificity status: **{candidate['specificity_status']}**",
                    f"- Docking score: **{_format_score(candidate['docking_score'])}**",
                    f"- Spatial rank: **{candidate['spatial_rank'] or 'n/a'}**",
                    f"- Spatial groups: {', '.join(candidate['detected_groups']) or 'none detected'}",
                ]
            )
    else:
        lines.extend(["", "No candidates were selected for docking in this run."])

    lines.extend(
        [
            "",
            "## Other Screened Candidates",
            "",
            (
                f"{overview.get('non_docked_candidate_count', 0)} candidate(s) were screened "
                "but not carried into docking."
            ),
        ]
    )
    if overview.get("non_docked_candidate_count"):
        lines.extend(
            [
                (
                    f"Score range: **{_format_score(overview.get('non_docked_score_min'))}** to "
                    f"**{_format_score(overview.get('non_docked_score_max'))}**."
                ),
                (
                    f"Specificity overview: {overview.get('specificity_status_counts', {})}. "
                    "Individual non-docked sequences are intentionally omitted."
                ),
            ]
        )
    lines.extend(
        [
            "",
            "Export this report with `export` or `/export`, or finish with `finish`.",
        ]
    )
    return "\n".join(lines)


def export_final_report_artifacts(
    persistence: Any,
    state: Any,
    markdown: str,
    context: dict[str, Any],
) -> tuple[Any, Any]:
    markdown_path = persistence.write_artifact(
        state.run_id,
        "final_report.md",
        markdown,
        mime_type="text/markdown",
    )
    sidecar = {
        "run_id": state.run_id,
        "report_context": context,
        "recommendations": [result.model_dump() for result in state.recommendations],
        "specificity_results": [result.model_dump() for result in state.specificity_results],
        "docking_results": [result.model_dump() for result in state.docking_results],
        "spatial_ranks": [result.model_dump() for result in state.spatial_ranks],
    }
    json_path = persistence.write_artifact(
        state.run_id,
        "final_report.json",
        sidecar,
    )
    return markdown_path, json_path


class ReportHandler(StepHandler):
    def enter(self) -> None:
        self.run_worker(self._build_report, activity="Compiling final report...")

    def _build_report(self) -> None:
        state = self.screen.app.current_state
        context = build_report_context(state)
        state.recommendations = [
            FinalRecommendation.model_validate(item)
            for item in [
                {
                    "candidate_id": candidate["candidate_id"],
                    "primary_score": candidate["primary_score"],
                    "specificity_status": candidate["specificity_status"],
                    "docking_score": candidate["docking_score"],
                    "spatial_rank": candidate["spatial_rank"],
                    "final_priority": candidate["final_priority"],
                }
                for candidate in context["docking_candidates"]
            ]
        ]
        state.final_report_context = context
        self.screen.app.save_state()

        markdown = ""
        try:
            skill = self.screen.app.runtime.create_skill(ReportSkill)
            if hasattr(self.screen.app, "_configure_llm_logging"):
                self.screen.app._configure_llm_logging(skill)
            chunks: list[str] = []
            bubble = None
            self.screen.app.call_from_thread(self.screen.clear_activity)
            for event in skill.write_markdown_stream(context):
                if isinstance(event, dict):
                    if event.get("type") != "content":
                        continue
                    text = event.get("text", "")
                else:
                    text = str(event)
                if not text:
                    continue
                chunks.append(text)
                if bubble is None:
                    def make_bubble() -> None:
                        nonlocal bubble
                        bubble = self.screen.add_streaming_message(markdown=True)

                    self.screen.app.call_from_thread(make_bubble)
                self.screen.app.call_from_thread(bubble.append_text, text)
            markdown = "".join(chunks).strip()
            if bubble is not None:
                self.screen.app.call_from_thread(bubble.finalize)
        except Exception:
            markdown = format_deterministic_report_markdown(context)
            self.screen.app.call_from_thread(
                self.screen.add_system_message, markdown, extra_class="", markdown=True,
            )

        if not markdown:
            markdown = format_deterministic_report_markdown(context)
            self.screen.app.call_from_thread(
                self.screen.add_system_message, markdown, extra_class="", markdown=True,
            )

        state.final_report_markdown = markdown
        self.screen.app.save_state()
        self.screen.app.call_from_thread(
            self.screen.add_system_message,
            "Report is ready. Type `export` to save Markdown, or `finish` to exit.",
            extra_class="",
            markdown=True,
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
        context = state.final_report_context or build_report_context(state)
        markdown = state.final_report_markdown or format_deterministic_report_markdown(
            context
        )
        md_path, json_path = export_final_report_artifacts(
            self.screen.app.persistence,
            state,
            markdown,
            context,
        )
        self.screen.add_system_message(
            f"Report exported to:\n- Markdown: `{md_path}`\n- Data sidecar: `{json_path}`",
            markdown=True,
        )
        self.screen.set_input_placeholder("Type 'finish' to exit")
