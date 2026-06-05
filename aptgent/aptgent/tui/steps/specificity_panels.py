from __future__ import annotations

from aptgent.domain.enums import Step
from aptgent.tui.widgets.structured_input import (
    ActionMenuPanel,
    AnalogCheckboxPanel,
)


class SpecificityPanelMixin:
    """Panel and phase helpers for the specificity step."""

    def _edit_recommended(self) -> None:
        recommendation = self.screen.app.current_state.context.specificity_recommendation
        if not recommendation.analog_names:
            self.screen.add_system_message(
                "No recommended analogs to edit. Switching to custom entry.",
                "warning-text",
            )
            self._customize()
            return
        recommendation.phase = "editing_recommended"
        recommendation.accepted = False
        self.screen.app.save_state()
        target = self.screen.app.current_state.target_molecule
        panel = AnalogCheckboxPanel(
            analog_names=recommendation.analog_names,
            target_name=target.input_text if target else "",
        )
        self.screen.add_structured_widget(panel)
        self.screen.set_input_enabled(True)
        self._refresh_input_placeholder()

    def _customize(self) -> None:
        recommendation = self.screen.app.current_state.context.specificity_recommendation
        recommendation.phase = "editing_custom"
        recommendation.accepted = False
        self.screen.app.save_state()
        self.screen.clear_structured_widget()
        self.screen.set_input_enabled(True)
        self._refresh_input_placeholder()

    def _return_to_custom_input(
        self,
        message: str = "Please try again with specific molecule names (e.g. 'caffeine and theobromine').",
    ) -> None:
        self._parse_in_flight = False
        self.screen.clear_structured_widget()
        self.screen.add_system_message(message, "warning-text")
        self.screen.set_input_enabled(True)
        self._refresh_input_placeholder()

    def _build_recommendation_choice_panel(self) -> ActionMenuPanel:
        choices: list[tuple[str, str, str]] = []
        intake_analogs = self.screen.app.current_state.context.intake.analogs
        if intake_analogs:
            choices.append(
                (
                    "use-intake-analogs",
                    "Use Initial Prompt Analogs",
                    f"Use the analogs you specified in your initial prompt: {', '.join(intake_analogs)}",
                )
            )
        choices.extend(
            [
                (
                    "accept-recommended-analogs",
                    "Accept Recommendations",
                    "Run specificity filtering immediately with the LLM-recommended analogs.",
                ),
                (
                    "edit-recommended-analogs",
                    "Partially Accept And Edit",
                    "Open an input box prefilled with the recommended analogs so you can adjust them.",
                ),
                (
                    "custom-analogs",
                    "Reject And Customize",
                    "Ignore the recommendations and enter your own analogs from scratch.",
                ),
                (
                    "skip-specificity",
                    "Skip This Step",
                    "Continue without specificity filtering.",
                ),
            ]
        )
        return ActionMenuPanel(
            Step.SPECIFICITY_FILTER,
            "Review the recommended analogs",
            choices,
        )

    def _show_recommendation_choice_panel(self) -> None:
        self.screen.add_structured_widget(self._build_recommendation_choice_panel())

    def _back_to_choices(self) -> None:
        recommendation = self.screen.app.current_state.context.specificity_recommendation
        recommendation.phase = "awaiting_decision"
        recommendation.accepted = False
        self.screen.app.save_state()
        self.screen.clear_structured_widget()
        self._show_recommendation_choice_panel()
        self.screen.set_input_enabled(True)
        self._refresh_input_placeholder()

    def _refresh_input_placeholder(self) -> None:
        phase = self.screen.app.current_state.context.specificity_recommendation.phase
        if phase == "awaiting_decision":
            self.screen.set_input_placeholder("Type 'accept', 'edit', 'custom', or 'skip'.")
        elif phase == "editing_custom":
            self.screen.set_input_placeholder(
                "Describe the analogs you want (e.g. 'just caffeine'), or type 'skip'."
            )
        elif phase == "editing_recommended":
            self.screen.set_input_placeholder(
                "Use the analog input box below, or type 'skip' to skip this step."
            )
        else:
            self.screen.set_input_placeholder("Preparing analog recommendations...")
