from __future__ import annotations

from aptgent.domain.enums import Step
from aptgent.llm.skills import SiteProposalSkill
from aptgent.tui.steps.base import StepHandler
from aptgent.tui.steps.common import (
    next_primary_step,
    run_llm_interaction,
    validate_site_proposal_result,
)
from aptgent.tui.steps.common.llm_ui import capture_streaming_result
from aptgent.tui.steps.empty_candidates import clear_site_selection_retry_feedback
from aptgent.tui.steps.state_reset import reset_after_site_selection
from aptgent.tui.widgets.structured_input import ActionMenuPanel, MutationSitePanel
from aptgent.workflow.context import (
    build_site_proposal_llm_context,
    get_sequence,
    record_site_proposal_context,
)


class SiteProposalHandler(StepHandler):
    def __init__(self, screen) -> None:
        super().__init__(screen)
        self._phase: str = "proposing"
        self._site_proposals: list[dict] = []
        self._proposed_sites: list[int] = []

    @property
    def allow_empty_input(self) -> bool:
        return self._phase == "awaiting_preference"

    def enter(self) -> None:
        state = self.screen.app.current_state
        proposal_context = state.context.site_proposal
        self._site_proposals = [dict(proposal) for proposal in proposal_context.proposals]
        self._proposed_sites = list(proposal_context.proposed_sites)
        struct = state.secondary_structure
        self._phase = "proposing"

        if struct is None:
            self.screen.add_system_message(
                "No secondary structure available. Skipping site proposal.",
                "warning-text",
            )
            ns = next_primary_step(Step.SITE_PROPOSAL)
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

        self._show_preference_prompt()

    def _show_preference_prompt(self) -> None:
        state = self.screen.app.current_state
        intake = state.context.intake
        self._phase = "awaiting_preference"

        existing_lines: list[str] = []
        if intake.modification_region:
            existing_lines.append(f"- **Modification region**: {intake.modification_region}")
        if intake.proposed_sites:
            existing_lines.append(
                f"- **Suggested sites from prompt**: {self._format_site_display(intake.proposed_sites)}"
            )

        lines: list[str] = []
        if existing_lines:
            lines.append("**Existing mutation requirements from your prompt:**")
            lines.append("")
            lines.extend(existing_lines)
            lines.append("")
            lines.append(
                "Type additional preferences below (regions, positions, constraints), "
                "or press Enter to proceed with these defaults."
            )
        else:
            lines.append(
                "Type mutation site preferences below (regions, positions, constraints), "
                "or press Enter to let the LLM recommend sites automatically."
            )

        self.screen.add_system_message("\n".join(lines), markdown=True)
        self.screen.set_input_placeholder(
            "Type mutation preference, or press Enter to skip."
        )
        self.screen.set_input_enabled(True)

    def _submit_preference(self, text: str) -> None:
        if not text.strip():
            self._phase = "proposing"
            self.run_worker(self._propose, activity="Analyzing mutation-tolerant sites...")
            return
        state = self.screen.app.current_state
        record_site_proposal_context(state, site_preference=text)
        self.screen.app.save_state()
        self.screen.add_system_message(f"Preference saved: {text}")
        self._phase = "proposing"
        self.run_worker(self._propose, activity="Analyzing mutation-tolerant sites...")

    def _propose(self) -> None:
        state = self.screen.app.current_state
        seq = get_sequence(state) or ""
        proposal_context = state.context.site_proposal
        previous_proposals = [dict(proposal) for proposal in proposal_context.proposals]
        preserve_indexes = set(proposal_context.preserve_proposal_indexes)

        if proposal_context.needs_regeneration and proposal_context.regeneration_reason:
            existing_feedback = dict(
                proposal_context.extra_context.get("site_selection_feedback") or {}
            )
            feedback = {
                **existing_feedback,
                "reason": "no_positive_candidates",
                "message": proposal_context.regeneration_reason,
                "selected_sites": list(state.confirmed_mutation_sites),
                "selection_source": proposal_context.selection_source,
                "selected_proposal_index": proposal_context.selected_proposal_index,
                "preserve_proposal_indexes": list(proposal_context.preserve_proposal_indexes),
                "previous_proposals": previous_proposals,
            }
            proposal_context.extra_context = {
                **dict(proposal_context.extra_context),
                "site_selection_feedback": feedback,
            }

        try:
            skill = self.screen.app.runtime.create_skill(SiteProposalSkill)
            self._threadsafe(
                self.screen.update_activity,
                "Preparing site-proposal context...",
            )
            llm_context = build_site_proposal_llm_context(state)
            supports_structured_events = hasattr(skill, "propose_events_from_context")

            if supports_structured_events:
                display_stream, get_captured = capture_streaming_result(
                    lambda: skill.propose_events_from_context(llm_context)
                )
            else:
                display_stream = None
                get_captured = lambda: {}

            def structured_result() -> dict:
                captured = get_captured()
                if captured:
                    return validate_site_proposal_result(captured, len(seq))
                if supports_structured_events:
                    raise RuntimeError("LLM structured result unavailable.")
                return validate_site_proposal_result(
                    skill.propose_from_context(llm_context),
                    len(seq),
                )

            result = run_llm_interaction(
                self.screen,
                display_stream=display_stream,
                structured_call=structured_result,
            )
        except Exception as exc:
            self._report_error(f"LLM error: {exc}")
            return

        proposals = result.get("proposals", [])
        region_assessment = result.get("region_assessment", [])
        if proposal_context.needs_regeneration and preserve_indexes:
            proposals = self._merge_regenerated_proposals(
                previous_proposals,
                proposals,
                preserve_indexes,
            )
        sites = result.get("proposed_sites", [])
        if proposals:
            first_proposal = proposals[0]
            sites = list(first_proposal.get("proposed_sites", []))
            reasoning = first_proposal.get("reasoning") or result.get("reasoning", "")
            confidence = first_proposal.get("confidence") or result.get("confidence", "")
        else:
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
            extra_context={
                **dict(proposal_context.extra_context),
                "region_assessment": region_assessment,
            },
            needs_regeneration=False,
            preserve_proposal_indexes=[],
        )
        self.screen.app.save_state()

        msg = self._format_proposals_message(
            proposals,
            sites,
            reasoning,
            confidence,
            region_assessment=region_assessment,
        )
        self._threadsafe(
            lambda: self.screen.add_system_message(msg, markdown=True)
        )

        self._threadsafe(self._show_choice_panel, proposals)
        self._threadsafe(
            self.screen.set_input_placeholder,
            "Type positions (e.g. 3,7,12) or choose a recommended plan.",
        )
        self._enable_input()

    def handle_user_input(self, text: str) -> None:
        if self._phase == "awaiting_preference":
            self._submit_preference(text)
            return

        state = self.screen.app.current_state
        seq = get_sequence(state) or ""
        text_lower = text.strip().lower()

        if text_lower in ("use suggestions", "confirm", "accept", "ok"):
            sites = self._proposed_sites
            source = "llm"
            proposal_index = 0
        elif text_lower in ("prompt", "use prompt") and state.context.intake.proposed_sites:
            sites = list(state.context.intake.proposed_sites)
            source = "intake"
            proposal_index = None
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
        if action == "use-intake-sites":
            state = self.screen.app.current_state
            sites = list(state.context.intake.proposed_sites)
            self._confirm_sites(sites, source="intake", proposal_index=None)
            return
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
                    self._proposed_sites,
                    source="llm",
                    proposal_index=0,
                )
            return
        if action == "use-recommended-sites":
            self._confirm_sites(
                self._proposed_sites,
                source="llm",
                proposal_index=0,
            )
            return
        if action == "custom-sites":
            state = self.screen.app.current_state
            seq = get_sequence(state) or ""
            panel = MutationSitePanel(seq, self._proposed_sites)
            self.screen.add_structured_widget(panel)
            self.screen.set_input_enabled(False)
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
        seq = get_sequence(state) or ""
        if seq and sites:
            before = len(sites)
            sites = [s for s in sites if 0 <= s < len(seq)]
            if len(sites) < before:
                self.screen.add_system_message(
                    f"Dropped {before - len(sites)} site(s) outside sequence range (length {len(seq)}).",
                    "warning-text",
                )
        state.set_mutation_sites(sites)
        context = state.context.site_proposal
        context.selection_source = source
        context.selected_proposal_index = proposal_index
        try:
            reset_after_site_selection(state, self.screen.app.persistence)
        except RuntimeError as exc:
            self.screen.add_system_message(str(exc), "error-text")
            self.screen.set_input_enabled(True)
            return
        clear_site_selection_retry_feedback(state)
        record_site_proposal_context(state, confirmed_sites=sites)
        self.screen.app.save_state()
        self.screen.add_system_message(f"Confirmed mutation sites: {sites}")
        ns = next_primary_step(Step.SITE_PROPOSAL)
        if ns:
            self.screen.advance_to_step(ns)

    @staticmethod
    def _format_proposals_message(
        proposals: list[dict],
        sites: list[int],
        reasoning: str,
        confidence: str,
        *,
        region_assessment: list[dict] | None = None,
    ) -> str:
        lines: list[str] = []
        if region_assessment:
            lines.append("Region assessment:")
            for region in region_assessment:
                label = region.get("label") or "Region"
                category = region.get("category") or "unknown"
                region_sites = region.get("positions") or []
                start = region.get("start")
                end = region.get("end")
                if region_sites:
                    scope = SiteProposalHandler._format_site_display(region_sites)
                elif start is not None and end is not None:
                    scope = SiteProposalHandler._format_site_display(
                        list(range(int(start), int(end) + 1))
                    )
                else:
                    scope = "positions unspecified"
                rationale = region.get("rationale") or "No rationale provided."
                region_confidence = region.get("confidence") or "unknown"
                lines.append(
                    f"- {label} ({category}, {region_confidence}): {scope} - {rationale}"
                )
            lines.append("")

        if not proposals:
            msg = f"Suggested sites: {sites}"
            if reasoning:
                msg += f"\nReason: {reasoning}"
            if confidence:
                msg += f"\nConfidence: {confidence}"
            lines.append(msg)
            return "\n".join(lines)
        lines.append("Suggested mutation-site plans:")
        for index, proposal in enumerate(proposals, start=1):
            label = proposal.get("label") or f"Plan {index}"
            proposal_sites = proposal.get("proposed_sites", [])
            proposal_reasoning = proposal.get("reasoning") or "No reason provided."
            proposal_confidence = proposal.get("confidence") or "unknown"
            lines.append(
                f"{index}. {label}: {SiteProposalHandler._format_site_display(proposal_sites)} "
                f"({proposal_confidence}) - {proposal_reasoning}"
            )
        return "\n".join(lines)

    @staticmethod
    def _format_site_display(sites: list[int]) -> str:
        zero_based = [int(site) for site in sites]
        one_based = [site + 1 for site in zero_based]
        return f"0-based {zero_based} / 1-based {one_based}"

    def _show_choice_panel(self, proposals: list[dict]) -> None:
        choices: list[tuple[str, str, str]] = []
        state = self.screen.app.current_state
        intake_sites = state.context.intake.proposed_sites
        if intake_sites:
            choices.append(
                (
                    "use-intake-sites",
                    "Use Initial Prompt Sites",
                    f"Use the sites you specified in your initial prompt: {self._format_site_display(intake_sites)}",
                )
            )
        if proposals:
            choices.extend(
                (
                    f"use-recommended-sites-{index}",
                    proposal.get("label") or f"Use Plan {index + 1}",
                    (
                        f"Accept positions {proposal.get('proposed_sites', [])}. "
                        f"{proposal.get('reasoning') or ''}"
                    ).strip(),
                )
                for index, proposal in enumerate(proposals)
            )
        else:
            sites = self._proposed_sites
            choices.append(
                (
                    "use-recommended-sites",
                    "Use Recommended Sites",
                    (
                        f"Accept the suggested positions immediately: {sites}"
                        if sites
                        else "No sites were suggested; continue with an empty selection."
                    ),
                )
            )
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
            region_assessment=list(context.extra_context.get("region_assessment") or []),
        )
        self.screen.add_system_message(msg, markdown=True)
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
