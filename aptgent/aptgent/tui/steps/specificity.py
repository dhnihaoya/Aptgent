from __future__ import annotations

from typing import Any

from aptgent.domain.enums import Step
from aptgent.domain.models import SpecificityResult, TargetMolecule
from aptgent.domain.ranking import select_top_y_by_affinity
from aptgent.llm.skills import AnalogParseSkill, AnalogSuggestionSkill
from aptgent.tui.steps.base import StepHandler
from aptgent.tui.steps.common import next_primary_step
from aptgent.tui.steps.job_progress import JobProgressTracker
from aptgent.tui.steps.job_mixin import JobAttachMixin
from aptgent.tui.steps.specificity_analogs import SpecificityAnalogMixin
from aptgent.tui.steps.specificity_panels import SpecificityPanelMixin
from aptgent.tui.steps.specificity_progress import SpecificityProgressMixin
from aptgent.tui.widgets.structured_input import AnalogCheckboxPanel
from aptgent.workflow.engine import step_display_number


class SpecificityHandler(
    SpecificityAnalogMixin,
    SpecificityPanelMixin,
    SpecificityProgressMixin,
    JobAttachMixin,
    StepHandler,
):
    """Specificity filter with detached cross-prediction job.

    The recommendation/edit phases stay in-process; once analogs are
    confirmed, the actual cross-prediction is dispatched to the detached
    ``specificity_filter`` job runner so progress streams back through the
    same ``events.jsonl`` protocol as candidate enumeration.
    """

    JOB_STEP = "specificity_filter"

    def __init__(self, screen: Any) -> None:
        super().__init__(screen)
        self._progress = JobProgressTracker()
        self._parse_in_flight = False

    def _analog_suggestion_skill(self):
        return AnalogSuggestionSkill

    def _analog_parse_skill(self):
        return AnalogParseSkill

    def enter(self) -> None:
        state = self.screen.app.current_state
        self._compute_affinity_selection(state)
        recommendation = state.context.specificity_recommendation
        self.screen.add_system_message(
            f"Step {step_display_number(Step.SPECIFICITY_FILTER)}: Specificity Filter\n"
            "The LLM will first suggest important analog molecules, then you can accept, edit, or replace them before filtering."
        )
        if recommendation.display_markdown and recommendation.phase in {
            "awaiting_decision",
            "editing_recommended",
            "editing_custom",
        }:
            self.screen.add_system_message(recommendation.display_markdown, markdown=True)

        if recommendation.phase == "awaiting_decision" and recommendation.analog_names:
            self._show_recommendation_choice_panel()
            self.screen.set_input_enabled(True)
        elif recommendation.phase == "editing_recommended":
            target = state.target_molecule
            panel = AnalogCheckboxPanel(
                analog_names=recommendation.analog_names,
                target_name=target.input_text if target else "",
            )
            self.screen.add_structured_widget(panel)
            self.screen.set_input_enabled(True)
        elif recommendation.phase == "editing_custom":
            self.screen.set_input_enabled(True)
        else:
            self._suggest()
        self._refresh_input_placeholder()

    def handle_user_input(self, text: str) -> None:
        text_lower = text.strip().lower()
        if text_lower == "skip":
            self._skip()
        elif text_lower in {"prompt", "use prompt"}:
            self._use_intake_analogs()
        elif text_lower in {"accept", "1"}:
            self._accept_recommended()
        elif text_lower in {"edit", "modify", "partial", "2"}:
            self._edit_recommended()
        elif text_lower in {"custom", "3"}:
            self._customize()
        else:
            recommendation = self.screen.app.current_state.context.specificity_recommendation
            if recommendation.phase == "editing_custom":
                self._parse_custom_analogs(text)
            elif recommendation.phase == "editing_recommended":
                self._run_filter(text, echo_user=False)

    def handle_structured_input(self, data: dict) -> None:
        action = data.get("action", "run")
        if action == "skip":
            self._skip()
        elif action == "retry_custom":
            self._return_to_custom_input(message="Enter the analogs you want to use.")
        elif action == "back":
            self._back_to_choices()
        else:
            analogs_text = data.get("analogs_text", "")
            self._run_filter(analogs_text, echo_user=bool(analogs_text.strip()))

    def handle_action(self, action: str) -> None:
        if action == "use-intake-analogs":
            self._use_intake_analogs()
        elif action == "accept-recommended-analogs":
            self._accept_recommended()
        elif action == "edit-recommended-analogs":
            self._edit_recommended()
        elif action == "custom-analogs":
            self._customize()
        elif action == "skip-specificity":
            self._skip()

    def _compute_affinity_selection(self, state: Any) -> None:
        if state.affinity_selected_ids:
            return
        docking_results = state.docking_results
        if not docking_results:
            state.affinity_selected_ids = [
                c.candidate_id for c in state.candidates
            ]
            self.screen.app.save_state()
            return
        plan = state.docking_plan
        top_y = (
            plan.affinity_top_k
            if plan and plan.affinity_top_k
            else state.context.docking_recommendation.recommended_affinity_top_k
            or min(5, len(docking_results))
        )
        selected = select_top_y_by_affinity(
            [r.model_dump() for r in docking_results],
            top_y,
        )
        state.affinity_selected_ids = selected
        self.screen.add_system_message(
            f"Selected top-{top_y} by binding affinity: "
            f"{len(selected)} sequences (ties included)."
        )
        self.screen.app.save_state()

    def _affinity_filtered_candidates(self, state: Any) -> list[Any]:
        """Return candidates filtered to the affinity-selected subset.

        Mirrors the filtering in ``runner._run_specificity`` so the TUI
        displays counts consistent with what the detached job processes.
        """
        candidates = list(state.candidates)
        selected_ids = set(state.affinity_selected_ids) if state.affinity_selected_ids else set()
        if selected_ids:
            candidates = [c for c in candidates if c.candidate_id in selected_ids]
        return candidates

    def _run_filter(self, analogs_text: str, *, echo_user: bool) -> None:
        if echo_user:
            self.screen.add_user_message(f"Filter with: {analogs_text}")

        state = self.screen.app.current_state
        candidates = self._affinity_filtered_candidates(state)

        if not analogs_text.strip():
            self.screen.add_system_message("No analogs provided. Nothing to filter.")
            self.screen.set_input_enabled(True)
            return

        analogs: list[TargetMolecule] = []
        for part in analogs_text.split(","):
            part = part.strip()
            if not part:
                continue
            resolved = self.screen.app.molecule_resolver.resolve(part)
            if resolved.resolution_status == "resolved":
                analogs.append(resolved)
            else:
                analogs.append(TargetMolecule(input_text=part, resolution_status="failed"))

        state.analogs = analogs
        self.screen.app.save_state()

        self.screen.clear_structured_widget()

        valid_analogs = [a for a in analogs if a.smiles]
        all_targets_count = 1 + len(valid_analogs)
        total_pairs = len(candidates) * all_targets_count

        self.screen.add_system_message(
            f"Running cross-prediction on {len(candidates)} candidates x "
            f"{all_targets_count} target(s) ({len(valid_analogs)} analog(s) + 1 primary)."
        )

        self._progress.reset(total=total_pairs)

        progress = self._create_progress_bubble(total_pairs)

        self.attach_or_spawn_job(
            on_event=lambda evt: self._on_job_event(evt, progress),
            on_done=lambda summary: self._on_job_done(summary, progress),
            on_error=lambda msg: self._on_job_error(msg),
            activity="Running specificity cross-prediction...",
        )

    def _skip(self) -> None:
        state = self.screen.app.current_state
        state.specificity_results = [
            SpecificityResult(candidate_id=c.candidate_id or "", status="skipped")
            for c in self._affinity_filtered_candidates(state)
        ]
        self.screen.app.save_state()
        self.screen.add_system_message("Specificity filter skipped.")
        ns = next_primary_step(Step.SPECIFICITY_FILTER)
        if ns:
            self.screen.advance_to_step(ns)
