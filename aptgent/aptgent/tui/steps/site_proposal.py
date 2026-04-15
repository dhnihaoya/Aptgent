from __future__ import annotations

from aptgent.domain.enums import Step
from aptgent.llm.skills import SiteProposalSkill
from aptgent.tui.steps.base import StepHandler
from aptgent.tui.steps.common import (
    next_step,
    run_llm_interaction,
    validate_site_proposal_result,
)
from aptgent.tui.widgets.structured_input import ActionMenuPanel, MutationSitePanel
from aptgent.workflow.context import (
    build_site_proposal_llm_context,
    get_sequence,
    record_site_proposal_context,
)


class SiteProposalHandler(StepHandler):
    def enter(self) -> None:
        state = self.screen.app.current_state
        struct = state.secondary_structure

        if struct is None:
            self.screen.add_system_message(
                "No secondary structure available. Skipping site proposal.",
                "warning-text",
            )
            ns = next_step(Step.SITE_PROPOSAL)
            if ns:
                self.screen.advance_to_step(ns)
            return

        self.run_worker(self._propose, activity="Analyzing mutation-tolerant sites...")

    def _propose(self) -> None:
        state = self.screen.app.current_state
        seq = get_sequence(state) or ""

        try:
            skill = SiteProposalSkill()
            self.screen.app.call_from_thread(
                self.screen.update_activity,
                "Preparing site-proposal context...",
            )
            llm_context = build_site_proposal_llm_context(state)
            result = run_llm_interaction(
                self.screen,
                display_stream=lambda: skill.explain_propose_stream_from_context(llm_context),
                structured_call=lambda: validate_site_proposal_result(
                    skill.propose_from_context(llm_context),
                    len(seq),
                ),
            )
        except Exception as exc:
            self.screen.app.call_from_thread(
                self.screen.add_system_message, f"LLM error: {exc}", "error-text"
            )
            self.screen.app.call_from_thread(self.screen.set_input_enabled, True)
            return

        sites = result.get("proposed_sites", [])
        reasoning = result.get("reasoning", "")
        confidence = result.get("confidence", "")
        self._proposed_sites = sites
        record_site_proposal_context(
            state,
            proposed_sites=sites,
            reasoning=reasoning,
            confidence=confidence,
            llm_context=llm_context,
        )
        self.screen.app.save_state()

        if reasoning:
            self.screen.app.call_from_thread(self.screen.add_system_message, reasoning)
        msg = f"Suggested sites: {sites}"
        if confidence:
            msg += f"\nConfidence: {confidence}"
        self.screen.app.call_from_thread(self.screen.add_system_message, msg)

        self.screen.app.call_from_thread(self._show_choice_panel, sites)
        self.screen.app.call_from_thread(
            self.screen.set_input_placeholder,
            "Type positions (e.g. 3,7,12) or 'use suggestions'.",
        )
        self.screen.app.call_from_thread(self.screen.set_input_enabled, True)

    def handle_user_input(self, text: str) -> None:
        state = self.screen.app.current_state
        seq = get_sequence(state) or ""
        text_lower = text.strip().lower()

        if text_lower in ("use suggestions", "confirm", "accept", "ok"):
            sites = getattr(self, "_proposed_sites", [])
        else:
            try:
                sites = [int(x.strip()) for x in text.split(",") if x.strip()]
                sites = [s for s in sites if 0 <= s < len(seq)]
            except ValueError:
                self.screen.add_system_message(
                    f"Could not parse positions from: {text}\n"
                    "Please use comma-separated integers (e.g. 3,7,12) or 'use suggestions'.",
                    "warning-text",
                )
                return

        self._confirm_sites(sites)

    def handle_structured_input(self, data: dict) -> None:
        sites = data.get("selected_sites", [])
        self._confirm_sites(sites)

    def handle_action(self, action: str) -> None:
        if action == "use-recommended-sites":
            self._confirm_sites(getattr(self, "_proposed_sites", []))
            return
        if action == "custom-sites":
            state = self.screen.app.current_state
            seq = get_sequence(state) or ""
            panel = MutationSitePanel(seq, getattr(self, "_proposed_sites", []))
            self.screen.add_structured_widget(panel)
            self.screen.set_input_placeholder(
                "Select sites in the panel, or type comma-separated positions."
            )

    def _confirm_sites(self, sites: list[int]) -> None:
        state = self.screen.app.current_state
        state.confirmed_mutation_sites = sites
        record_site_proposal_context(state, confirmed_sites=sites)
        self.screen.app.save_state()
        self.screen.add_system_message(f"Confirmed mutation sites: {sites}")
        ns = next_step(Step.SITE_PROPOSAL)
        if ns:
            self.screen.advance_to_step(ns)

    def _show_choice_panel(self, sites: list[int]) -> None:
        panel = ActionMenuPanel(
            Step.SITE_PROPOSAL,
            "Choose how to select mutable sites",
            [
                (
                    "use-recommended-sites",
                    "Use Recommended Sites",
                    f"Accept the suggested positions immediately: {sites}" if sites else "No sites were suggested; continue with an empty selection.",
                ),
                (
                    "custom-sites",
                    "Customize Sites",
                    "Review the full sequence and choose positions yourself.",
                ),
            ],
        )
        self.screen.add_structured_widget(panel)
