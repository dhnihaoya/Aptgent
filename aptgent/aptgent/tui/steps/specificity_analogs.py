from __future__ import annotations

from aptgent.tui.steps.common import (
    format_specificity_recommendation_markdown,
    run_llm_interaction,
    validate_analog_suggestion_result,
)
from aptgent.tui.steps.common.llm_ui import capture_streaming_result
from aptgent.tui.widgets.structured_input import AnalogCustomPanel
from aptgent.workflow.context import record_specificity_recommendation_context


class SpecificityAnalogMixin:
    """LLM suggestion and custom analog parsing helpers."""

    def _suggest(self) -> None:
        self.run_worker(self._suggest_worker, activity="Suggesting analog molecules...")

    def _suggest_worker(self) -> None:
        target = self.screen.app.current_state.target_molecule

        try:
            skill = self.screen.app.runtime.create_skill(self._analog_suggestion_skill())
            display_stream, get_captured = capture_streaming_result(
                lambda: skill.suggest_events(target)
            )

            def structured_result() -> dict:
                captured = get_captured()
                if captured:
                    return validate_analog_suggestion_result(captured)
                raise RuntimeError("LLM structured result unavailable.")

            result = run_llm_interaction(
                self.screen,
                display_stream=display_stream,
                structured_call=structured_result,
            )
            analogs = result.get("analogs", [])
            note = result.get("note", "")
            analog_names = [a.get("name", "") for a in analogs if a.get("name")]
            markdown = format_specificity_recommendation_markdown(
                target_name=(target.resolved_name or target.input_text) if target else "",
                analogs=analogs,
                note=note,
            )
            state = self.screen.app.current_state
            record_specificity_recommendation_context(
                state,
                analog_names=analog_names,
                display_markdown=markdown,
                note=note,
                phase="awaiting_decision" if analog_names else "editing_custom",
                accepted=False,
            )
            self.screen.app.save_state()
            if markdown:
                self._threadsafe(
                    lambda md=markdown: self.screen.add_system_message(md, markdown=True)
                )
            if analog_names:
                self._threadsafe(self._show_recommendation_choice_panel)
            else:
                self._threadsafe(
                    self.screen.add_system_message,
                    "No analog suggestions were returned. Enter your own analogs or skip this step.",
                )
                self._threadsafe(self._customize)
            self._enable_input()
            self._threadsafe(self._refresh_input_placeholder)
        except Exception as exc:
            self._threadsafe(
                self.screen.add_system_message, f"Suggestion failed: {exc}", "error-text"
            )
            state = self.screen.app.current_state
            record_specificity_recommendation_context(
                state,
                analog_names=[],
                display_markdown="",
                note="",
                phase="editing_custom",
                accepted=False,
            )
            self.screen.app.save_state()
            self._threadsafe(self._customize)
            self._enable_input()
            self._threadsafe(self._refresh_input_placeholder)

    def _recommended_analogs_text(self) -> str:
        analog_names = self.screen.app.current_state.context.specificity_recommendation.analog_names
        return ", ".join(analog_names)

    def _accept_recommended(self) -> None:
        analogs_text = self._recommended_analogs_text()
        if not analogs_text:
            self.screen.add_system_message(
                "No recommended analogs are available to accept. Enter your own analogs instead.",
                "warning-text",
            )
            self._customize()
            return
        recommendation = self.screen.app.current_state.context.specificity_recommendation
        recommendation.accepted = True
        self.screen.app.save_state()
        self._run_filter(analogs_text, echo_user=False)

    def _use_intake_analogs(self) -> None:
        intake_analogs = self.screen.app.current_state.context.intake.analogs
        if not intake_analogs:
            self.screen.add_system_message(
                "No analogs were provided in the initial prompt.",
                "warning-text",
            )
            return
        analogs_text = ", ".join(intake_analogs)
        self.screen.add_user_message(f"Use initial prompt analogs: {analogs_text}")
        recommendation = self.screen.app.current_state.context.specificity_recommendation
        recommendation.accepted = True
        self.screen.app.save_state()
        self._run_filter(analogs_text, echo_user=False)

    def _parse_custom_analogs(self, text: str) -> None:
        if self._parse_in_flight:
            return
        self._parse_in_flight = True
        self.run_worker(
            lambda: self._parse_custom_worker(text),
            activity="Parsing analog request...",
        )

    def _parse_custom_worker(self, text: str) -> None:
        try:
            skill = self.screen.app.runtime.create_skill(self._analog_parse_skill())
            display_stream, get_captured = capture_streaming_result(
                lambda: skill.parse_events(text)
            )

            def structured_result() -> dict:
                captured = get_captured()
                if captured:
                    return captured
                result = skill.invoke(text)
                return result.raw if hasattr(result, "raw") else result

            result = run_llm_interaction(
                self.screen,
                display_stream=display_stream,
                structured_call=structured_result,
            )

            molecule_names = list(dict.fromkeys(
                n for n in (m.strip() for m in result.get("molecule_names", [])) if n
            ))
            if not molecule_names:
                self._threadsafe(
                    self.screen.add_system_message,
                    "Could not identify any molecule names from your request. "
                    "Please try again with specific molecule names (e.g. 'caffeine and theobromine').",
                    "warning-text",
                )
                self._threadsafe(self._return_to_custom_input)
                return

            resolved_pairs: list[tuple[str, bool]] = []
            resolved_names: list[str] = []
            for name in molecule_names:
                resolved = self.screen.app.molecule_resolver.resolve(name)
                if resolved.resolution_status == "resolved":
                    resolved_pairs.append((name, True))
                    resolved_names.append(name)
                else:
                    resolved_pairs.append((name, False))

            if not resolved_names:
                self._threadsafe(
                    self.screen.add_system_message,
                    f"None of the identified molecules could be resolved: "
                    f"{', '.join(name for name, _ in resolved_pairs)}. "
                    "Please check the names and try again.",
                    "error-text",
                )
                self._threadsafe(self._return_to_custom_input)
                return

            def _confirm():
                self._parse_in_flight = False
                target = self.screen.app.current_state.target_molecule
                panel = AnalogCustomPanel(
                    target_name=target.input_text if target else "",
                    resolved_pairs=resolved_pairs,
                )
                self.screen.add_structured_widget(panel)

            self._threadsafe(_confirm)

        except Exception as exc:
            self._threadsafe(
                self.screen.add_system_message,
                f"Failed to parse request: {exc}",
                "error-text",
            )
            self._threadsafe(self._return_to_custom_input)
