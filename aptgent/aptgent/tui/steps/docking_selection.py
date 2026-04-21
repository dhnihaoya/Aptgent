from __future__ import annotations

from aptgent.adapters.docking import HardwareProbeAdapter
from aptgent.domain.enums import Step
from aptgent.domain.models import DockingPlan
from aptgent.llm.skills import DockingPlannerSkill
from aptgent.tui.steps.base import StepHandler
from aptgent.tui.steps.common import (
    compute_deterministic_docking_plan,
    format_docking_recommendation_markdown,
    next_step,
    run_llm_interaction,
    validate_docking_recommendation_result,
)
from aptgent.tui.widgets.structured_input import (
    ActionMenuPanel,
    DockingParamPanel,
    DockingStrategyPanel,
)
from aptgent.workflow.context import record_docking_recommendation_context
from aptgent.workflow.context import record_tertiary_structure_context


class DockingSelectionHandler(StepHandler):
    def enter(self) -> None:
        state = self.screen.app.current_state
        recommendation = state.context.docking_recommendation

        self.screen.add_system_message(
            f"Step 7: Docking Selection\n"
            f"{len(state.candidates)} candidates available for docking."
        )
        if recommendation.display_markdown and recommendation.phase in {"awaiting_decision", "editing_form"}:
            self.screen.add_system_message(recommendation.display_markdown, markdown=True)
        if recommendation.phase == "editing_form":
            self._show_docking_panel()
        elif recommendation.phase == "awaiting_decision" and recommendation.recommended_top_k > 0:
            self._show_recommendation_choice_panel()
        else:
            self._show_strategy_panel()
        self.screen.set_input_enabled(True)
        if recommendation.phase == "awaiting_decision":
            self.screen.set_input_placeholder("Accept the LLM draft, adjust it, or skip docking.")
        elif recommendation.phase == "editing_form":
            self.screen.set_input_placeholder("Review the docking parameters and submit when ready.")
        else:
            self.screen.set_input_placeholder("Enter an optional time budget, then choose how to prepare docking.")

    def handle_user_input(self, text: str) -> None:
        if "skip" in text.strip().lower():
            self._skip()

    def handle_structured_input(self, data: dict) -> None:
        state = self.screen.app.current_state
        top_k = data.get("top_k", 0)
        candidate_count = len(state.candidates)

        if top_k <= 0:
            self.screen.add_system_message("Please enter a valid top-k > 0.", "warning-text")
            return
        if candidate_count and top_k > candidate_count:
            top_k = candidate_count

        recommendation = state.context.docking_recommendation
        profile = recommendation.machine_profile or HardwareProbeAdapter().probe()
        state.docking_plan = DockingPlan(
            machine_profile=profile,
            time_budget=data.get("time_budget"),
            recommended_top_k=top_k,
            reason=data.get("recommendation_reason", ""),
            receptor_path=data.get("receptor_path"),
            grid_center=data.get("grid_center"),
            grid_size=data.get("grid_size"),
            exhaustiveness=data.get("exhaustiveness"),
        )
        record_tertiary_structure_context(
            state,
            provider="rnacomposer",
            receptor_source="manual_input",
            receptor_status="provided" if data.get("receptor_path") else "pending",
            result_path=data.get("receptor_path"),
            error="",
        )
        state.time_budget = data.get("time_budget")
        recommendation.accepted = bool(data.get("accepted_recommendation"))
        recommendation.phase = "editing_form"
        self.screen.app.save_state()
        self.screen.add_system_message(
            f"Docking plan: top-{top_k} candidates, "
            f"receptor={data.get('receptor_path', 'N/A')}"
        )
        ns = next_step(Step.DOCKING_SELECTION)
        if ns:
            self.screen.advance_to_step(ns)

    def handle_action(self, action: str) -> None:
        if action.startswith("strategy:"):
            self._handle_strategy_action(action)
            return
        if action == "accept-docking-recommendation":
            recommendation = self.screen.app.current_state.context.docking_recommendation
            recommendation.accepted = True
            recommendation.phase = "editing_form"
            recommendation.strategy = "llm"
            self.screen.app.save_state()
            self._show_docking_panel()
            self.screen.set_input_enabled(True)
            return
        if action == "customize-after-recommendation":
            recommendation = self.screen.app.current_state.context.docking_recommendation
            recommendation.accepted = False
            recommendation.phase = "editing_form"
            recommendation.strategy = "llm"
            self.screen.app.save_state()
            self._show_docking_panel()
            self.screen.set_input_enabled(True)
            return
        if action == "skip-docking":
            self._skip()

    def _handle_strategy_action(self, action: str) -> None:
        _, strategy, *rest = action.split(":")
        budget_str = rest[0] if rest else ""
        time_budget = int(budget_str) if budget_str.isdigit() else None
        state = self.screen.app.current_state
        if time_budget is not None:
            state.time_budget = time_budget
        recommendation = state.context.docking_recommendation
        if not recommendation.machine_profile:
            recommendation.machine_profile = HardwareProbeAdapter().probe()
        recommendation.time_budget_hours = time_budget or state.time_budget
        self.screen.app.save_state()
        if strategy == "llm":
            self.run_worker(
                lambda: self._recommend_worker(recommendation.time_budget_hours),
                activity="Preparing an LLM docking draft...",
            )
            return
        if strategy == "manual":
            recommendation.strategy = "manual"
            recommendation.phase = "editing_form"
            recommendation.accepted = False
            self.screen.app.save_state()
            self._show_docking_panel()
            self.screen.set_input_enabled(True)
            return
        if strategy == "skip":
            self._skip()

    def _recommend_worker(self, time_budget: int | None) -> None:
        state = self.screen.app.current_state
        profile = HardwareProbeAdapter().probe()

        candidate_count = len(state.candidates)
        target_smiles = state.target_molecule.smiles if state.target_molecule else None
        target_name = (
            state.target_molecule.resolved_name or state.target_molecule.input_text
            if state.target_molecule else None
        )
        deterministic_plan = compute_deterministic_docking_plan(
            candidate_count=candidate_count,
            machine_profile=profile,
            time_budget_hours=time_budget,
            target_smiles=target_smiles,
        )
        computed_top_k = deterministic_plan["recommended_top_k"]
        computed_time_budget = deterministic_plan["recommended_time_budget_hours"]
        computed_grid_size = deterministic_plan["recommended_grid_size"]
        computed_exhaustiveness = deterministic_plan["recommended_exhaustiveness"]

        try:
            skill = DockingPlannerSkill()
            result = run_llm_interaction(
                self.screen,
                display_stream=lambda: skill.explain_plan_stream(
                    candidate_count=candidate_count,
                    machine_profile=profile,
                    time_budget_hours=time_budget,
                    computed_top_k=computed_top_k,
                    computed_time_budget_hours=computed_time_budget,
                    computed_grid_size=computed_grid_size,
                    target_smiles=target_smiles,
                    target_name=target_name,
                ),
                structured_call=lambda: validate_docking_recommendation_result(
                    skill.plan(
                        candidate_count=candidate_count,
                        machine_profile=profile,
                        time_budget_hours=time_budget,
                        computed_top_k=computed_top_k,
                        computed_time_budget_hours=computed_time_budget,
                        computed_grid_size=computed_grid_size,
                        target_smiles=target_smiles,
                        target_name=target_name,
                    ),
                    candidate_count=candidate_count,
                    machine_profile=profile,
                    time_budget_hours=time_budget,
                    target_smiles=target_smiles,
                ),
            )
            recommended_time_budget = result.get("recommended_time_budget_hours")
            top_k = result.get("recommended_top_k", 0)
            grid_size = result.get("recommended_grid_size", [])
            exhaustiveness = result.get("recommended_exhaustiveness") or computed_exhaustiveness
            receptor_path_note = result.get("receptor_path_note", "")
            grid_center_note = result.get("grid_center_note", "")
            reason = result.get("reason", "")
            markdown = format_docking_recommendation_markdown(
                candidate_count=len(state.candidates),
                machine_profile=profile,
                time_budget_hours=recommended_time_budget,
                recommended_top_k=top_k,
                recommended_grid_size=grid_size,
                recommended_exhaustiveness=exhaustiveness,
                receptor_path_note=receptor_path_note,
                grid_center_note=grid_center_note,
                reason=reason,
            )
            record_docking_recommendation_context(
                state,
                candidate_count=len(state.candidates),
                machine_profile=profile,
                time_budget_hours=time_budget,
                recommended_time_budget_hours=recommended_time_budget,
                recommended_top_k=top_k,
                recommended_grid_size=grid_size,
                recommended_exhaustiveness=exhaustiveness,
                receptor_path_note=receptor_path_note,
                grid_center_note=grid_center_note,
                reason=reason,
                display_markdown=markdown,
                strategy="llm",
                phase="awaiting_decision",
            )
            state.time_budget = recommended_time_budget
            self.screen.app.save_state()
            self.screen.app.call_from_thread(self._show_recommendation_choice_panel)
        except Exception as exc:
            self.screen.app.call_from_thread(
                self.screen.add_system_message, f"Recommendation failed: {exc}", "error-text"
            )
        finally:
            self.screen.app.call_from_thread(self.screen.set_input_enabled, True)

    @staticmethod
    def _build_recommendation_choice_panel(top_k: int) -> ActionMenuPanel:
        return ActionMenuPanel(
            Step.DOCKING_SELECTION,
            "Review the LLM docking draft",
            [
                (
                    "accept-docking-recommendation",
                    "Accept LLM Draft",
                    f"Load the suggested top-{top_k} setup into the final parameter form.",
                ),
                (
                    "customize-after-recommendation",
                    "Adjust Parameters",
                    "Open the same parameter form, prefilled with the LLM draft so you can edit it.",
                ),
                (
                    "skip-docking",
                    "Skip Docking",
                    "Continue directly to spatial ranking without docking.",
                ),
            ],
        )

    def _show_strategy_panel(self) -> None:
        recommendation = self.screen.app.current_state.context.docking_recommendation
        self.screen.add_structured_widget(
            DockingStrategyPanel(
                machine_profile=recommendation.machine_profile or HardwareProbeAdapter().probe(),
                time_budget=self.screen.app.current_state.time_budget,
            )
        )
        self.screen.set_input_placeholder("Enter an optional time budget, then choose LLM draft or manual setup.")

    def _show_recommendation_choice_panel(self) -> None:
        recommendation = self.screen.app.current_state.context.docking_recommendation
        self.screen.add_structured_widget(
            self._build_recommendation_choice_panel(recommendation.recommended_top_k)
        )
        self.screen.set_input_placeholder("Accept the LLM draft, adjust it, or skip docking.")

    def _show_docking_panel(self) -> None:
        state = self.screen.app.current_state
        recommendation = state.context.docking_recommendation
        self.screen.add_structured_widget(
            DockingParamPanel(
                mode="llm" if recommendation.strategy == "llm" else "manual",
                machine_profile=recommendation.machine_profile or HardwareProbeAdapter().probe(),
                time_budget=(
                    state.docking_plan.time_budget
                    if state.docking_plan and state.docking_plan.time_budget is not None
                    else state.time_budget
                    or recommendation.recommended_time_budget_hours
                    or recommendation.time_budget_hours
                ),
                recommended_top_k=recommendation.recommended_top_k,
                recommended_grid_size=recommendation.recommended_grid_size,
                recommended_exhaustiveness=(
                    state.docking_plan.exhaustiveness
                    if state.docking_plan and state.docking_plan.exhaustiveness is not None
                    else recommendation.recommended_exhaustiveness
                ),
                recommendation_reason=recommendation.reason,
                receptor_path_note=recommendation.receptor_path_note,
                grid_center_note=recommendation.grid_center_note,
                accepted_recommendation=recommendation.accepted,
                receptor_path=state.docking_plan.receptor_path if state.docking_plan else None,
                grid_center=state.docking_plan.grid_center if state.docking_plan else None,
                grid_size=(
                    state.docking_plan.grid_size
                    if state.docking_plan and state.docking_plan.grid_size
                    else recommendation.recommended_grid_size
                ),
            )
        )
        recommendation.phase = "editing_form"
        self.screen.set_input_placeholder("Review the docking parameters and submit when ready.")
        self.screen.app.save_state()

    def _skip(self) -> None:
        state = self.screen.app.current_state
        state.docking_plan = None
        state.docking_results = []
        record_tertiary_structure_context(
            state,
            provider="rnacomposer",
            receptor_source="manual_input",
            receptor_status="skipped",
            result_path="",
            error="",
        )
        recommendation = state.context.docking_recommendation
        recommendation.display_markdown = ""
        recommendation.reason = ""
        recommendation.phase = "skipped"
        recommendation.strategy = "skipped"
        recommendation.accepted = False
        recommendation.recommended_top_k = 0
        recommendation.recommended_grid_size = []
        recommendation.recommended_time_budget_hours = None
        recommendation.receptor_path_note = ""
        recommendation.grid_center_note = ""
        self.screen.app.save_state()
        self.screen.add_system_message("Docking skipped.")
        ns = next_step(Step.DOCKING_SELECTION)
        if ns:
            self.screen.advance_to_step(ns)
