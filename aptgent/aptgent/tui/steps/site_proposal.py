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
        proposal_context = state.context.site_proposal
        self._site_proposals = [dict(proposal) for proposal in proposal_context.proposals]
        self._proposed_sites = list(proposal_context.proposed_sites)
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

        if self._site_proposals or self._proposed_sites:
            if proposal_context.needs_regeneration:
                self.run_worker(
                    self._propose,
                    activity="Revising mutation-site recommendations...",
                )
                return
            self._show_existing_choices()
            return

        self.run_worker(self._propose, activity="Analyzing mutation-tolerant sites...")

    def _propose(self) -> None:
        state = self.screen.app.current_state
        seq = get_sequence(state) or ""
        proposal_context = state.context.site_proposal
        previous_proposals = [dict(proposal) for proposal in proposal_context.proposals]
        preserve_indexes = set(proposal_context.preserve_proposal_indexes)

        if proposal_context.needs_regeneration and proposal_context.regeneration_reason:
            feedback = {
                "reason": "no_positive_candidates",
                "message": proposal_context.regeneration_reason,
                "selected_sites": list(state.confirmed_mutation_sites),
                "selection_source": proposal_context.selection_source,
                "selected_proposal_index": proposal_context.selected_proposal_index,
            }
            proposal_context.extra_context = {
                **dict(proposal_context.extra_context),
                "site_selection_feedback": feedback,
            }

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

        proposals = result.get("proposals", [])
        if proposal_context.needs_regeneration and preserve_indexes:
            proposals = self._merge_regenerated_proposals(
                previous_proposals,
                proposals,
                preserve_indexes,
            )
        sites = result.get("proposed_sites", [])
        if proposals:
            sites = list(proposals[0].get("proposed_sites", []))
        reasoning = result.get("reasoning", "")
        confidence = result.get("confidence", "")
        self._site_proposals = proposals
        self._proposed_sites = sites
        proposal_context.needs_regeneration = False
        proposal_context.regeneration_reason = None
        proposal_context.preserve_proposal_indexes = []
        record_site_proposal_context(
            state,
            proposals=proposals,
            proposed_sites=sites,
            reasoning=reasoning,
            confidence=confidence,
            llm_context=llm_context,
            needs_regeneration=False,
            preserve_proposal_indexes=[],
        )
        self.screen.app.save_state()

        msg = self._format_proposals_message(proposals, sites, reasoning, confidence)
        self.screen.app.call_from_thread(self.screen.add_system_message, msg)

        self.screen.app.call_from_thread(self._show_choice_panel, proposals)
        self.screen.app.call_from_thread(
            self.screen.set_input_placeholder,
            "Type positions (e.g. 3,7,12) or choose a recommended plan.",
        )
        self.screen.app.call_from_thread(self.screen.set_input_enabled, True)

    def handle_user_input(self, text: str) -> None:
        state = self.screen.app.current_state
        seq = get_sequence(state) or ""
        text_lower = text.strip().lower()

        if text_lower in ("use suggestions", "confirm", "accept", "ok"):
            sites = getattr(self, "_proposed_sites", [])
            source = "llm"
            proposal_index = 0
        else:
            try:
                sites = [int(x.strip()) for x in text.split(",") if x.strip()]
                sites = [s for s in sites if 0 <= s < len(seq)]
                source = "custom"
                proposal_index = None
            except ValueError:
                self.screen.add_system_message(
                    f"Could not parse positions from: {text}\n"
                    "Please use comma-separated integers (e.g. 3,7,12) or 'use suggestions'.",
                    "warning-text",
                )
                return

        self._confirm_sites(sites, source=source, proposal_index=proposal_index)

    def handle_structured_input(self, data: dict) -> None:
        sites = data.get("selected_sites", [])
        self._confirm_sites(sites, source="custom", proposal_index=None)

    def handle_action(self, action: str) -> None:
        if action.startswith("use-recommended-sites-"):
            try:
                index = int(action.rsplit("-", 1)[1])
            except ValueError:
                index = 0
            proposals = getattr(self, "_site_proposals", [])
            if 0 <= index < len(proposals):
                self._confirm_sites(
                    list(proposals[index].get("proposed_sites", [])),
                    source="llm",
                    proposal_index=index,
                )
            else:
                self._confirm_sites(
                    getattr(self, "_proposed_sites", []),
                    source="llm",
                    proposal_index=0,
                )
            return
        if action == "use-recommended-sites":
            self._confirm_sites(
                getattr(self, "_proposed_sites", []),
                source="llm",
                proposal_index=0,
            )
            return
        if action == "custom-sites":
            state = self.screen.app.current_state
            seq = get_sequence(state) or ""
            panel = MutationSitePanel(seq, getattr(self, "_proposed_sites", []))
            self.screen.add_structured_widget(panel)
            self.screen.set_input_placeholder(
                "Select sites in the panel, or type comma-separated positions."
            )

    def _confirm_sites(
        self,
        sites: list[int],
        *,
        source: str,
        proposal_index: int | None,
    ) -> None:
        state = self.screen.app.current_state
        state.confirmed_mutation_sites = sites
        state.candidates = []
        state.predictions = []
        context = state.context.site_proposal
        context.selection_source = source
        context.selected_proposal_index = proposal_index
        context.needs_regeneration = False
        context.regeneration_reason = None
        context.preserve_proposal_indexes = []
        record_site_proposal_context(state, confirmed_sites=sites)
        self.screen.app.save_state()
        self.screen.add_system_message(f"Confirmed mutation sites: {sites}")
        ns = next_step(Step.SITE_PROPOSAL)
        if ns:
            self.screen.advance_to_step(ns)

    @staticmethod
    def _format_proposals_message(
        proposals: list[dict],
        sites: list[int],
        reasoning: str,
        confidence: str,
    ) -> str:
        if not proposals:
            msg = f"Suggested sites: {sites}"
            if reasoning:
                msg += f"\nReason: {reasoning}"
            if confidence:
                msg += f"\nConfidence: {confidence}"
            return msg
        lines = ["Suggested mutation-site plans:"]
        for index, proposal in enumerate(proposals, start=1):
            label = proposal.get("label") or f"Plan {index}"
            proposal_sites = proposal.get("proposed_sites", [])
            proposal_reasoning = proposal.get("reasoning") or "No reason provided."
            proposal_confidence = proposal.get("confidence") or "unknown"
            lines.append(
                f"{index}. {label}: {proposal_sites} "
                f"({proposal_confidence}) - {proposal_reasoning}"
            )
        return "\n".join(lines)

    def _show_choice_panel(self, proposals: list[dict]) -> None:
        if proposals:
            choices = [
                (
                    f"use-recommended-sites-{index}",
                    proposal.get("label") or f"Use Plan {index + 1}",
                    (
                        f"Accept positions {proposal.get('proposed_sites', [])}. "
                        f"{proposal.get('reasoning') or ''}"
                    ).strip(),
                )
                for index, proposal in enumerate(proposals)
            ]
        else:
            sites = getattr(self, "_proposed_sites", [])
            choices = [
                (
                    "use-recommended-sites",
                    "Use Recommended Sites",
                    (
                        f"Accept the suggested positions immediately: {sites}"
                        if sites
                        else "No sites were suggested; continue with an empty selection."
                    ),
                )
            ]
        choices.append(
            (
                "custom-sites",
                "Customize Sites",
                "Review the full sequence and choose positions yourself.",
            )
        )
        panel = ActionMenuPanel(
            Step.SITE_PROPOSAL,
            "Choose how to select mutable sites",
            choices,
            expanded=True,
        )
        self.screen.add_structured_widget(panel)

    def _show_existing_choices(self) -> None:
        state = self.screen.app.current_state
        context = state.context.site_proposal
        if context.regeneration_reason:
            self.screen.add_system_message(context.regeneration_reason, "warning-text")
        msg = self._format_proposals_message(
            self._site_proposals,
            self._proposed_sites,
            context.reasoning or "",
            context.confidence or "",
        )
        self.screen.add_system_message(msg)
        self._show_choice_panel(self._site_proposals)
        self.screen.set_input_placeholder(
            "Type positions (e.g. 3,7,12) or choose a recommended plan."
        )
        self.screen.set_input_enabled(True)

    @staticmethod
    def _merge_regenerated_proposals(
        previous: list[dict],
        regenerated: list[dict],
        preserve_indexes: set[int],
    ) -> list[dict]:
        if not previous:
            return regenerated
        merged: list[dict] = []
        regenerated_iter = iter(regenerated)
        target_len = max(len(previous), len(regenerated), 3)
        for index in range(target_len):
            if index in preserve_indexes and index < len(previous):
                merged.append(dict(previous[index]))
                continue
            try:
                merged.append(dict(next(regenerated_iter)))
            except StopIteration:
                if index < len(previous):
                    merged.append(dict(previous[index]))
        return merged[:3]
