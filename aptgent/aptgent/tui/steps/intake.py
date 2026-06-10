from __future__ import annotations

from aptgent.adapters.pdb_analysis import normalize_pdb_id
from aptgent.domain.enums import Step
from aptgent.domain.models import TargetMolecule
from aptgent.tui.steps.base import StepHandler
from aptgent.tui.steps.common import (
    clean_text,
    format_intake_confirmation,
    format_initial_intake_prompt,
    section_heading,
    INITIAL_INTAKE_PLACEHOLDER,
    next_primary_step,
    run_llm_interaction,
    validate_intake_result,
)
from aptgent.tui.steps.intake_heuristics import looks_like_full_intake
from aptgent.tui.steps.intake_resolver import resolve_target_text
from aptgent.tui.steps.pdb_intake import PdbIntakeHelper
from aptgent.workflow.context import (
    get_sequence,
    record_intake_context,
    record_pdb_intake_context,
)


def _resolution_error_message(
    target_text: str,
    resolved: TargetMolecule | None,
    *,
    source: str = "direct",
) -> str:
    """Build a context-appropriate retry message based on failure type."""
    detail = getattr(resolved, "error_detail", None) if resolved else None
    if detail == "network":
        msg = (
            f"PubChem lookup for `{target_text}` failed due to a network error "
            "after multiple retries. "
        )
        if source == "intake":
            msg += (
                "Please try again, paste a full intake brief to rerun extraction, "
                "or provide the SMILES string directly."
            )
        else:
            msg += (
                "Please try again, or provide the SMILES string directly."
            )
        return msg
    # Default: name not found or unknown failure
    if source == "intake":
        return (
            f"Could not resolve `{target_text}` from the current intake. "
            "Enter a corrected molecule name or SMILES, or paste a full intake brief to rerun extraction."
        )
    return (
        f"Could not resolve `{target_text}`. "
        "Please correct the molecule name or provide a valid SMILES string."
    )


class IntakeHandler(StepHandler):
    _INITIAL_PLACEHOLDER = INITIAL_INTAKE_PLACEHOLDER
    _TARGET_RETRY_PLACEHOLDER = (
        "Enter a corrected molecule name or SMILES, or paste a full intake brief."
    )
    _MISSING_TARGET_PLACEHOLDER = (
        "Enter the target molecule name or SMILES, or paste a new full intake brief."
    )
    _GENERAL_RETRY_PLACEHOLDER = (
        "Enter a valid PDB ID, sequence + target, or paste a new intake brief."
    )

    def __init__(self, screen) -> None:
        super().__init__(screen)
        self._pdb_helper = PdbIntakeHelper(
            screen,
            resolve_and_complete=self._resolve_and_complete,
            activate_general_retry=self._activate_general_retry,
        )

    def enter(self) -> None:
        state = self.screen.app.current_state
        intake = state.context.intake
        pdb_ctx = state.context.pdb_intake
        sequence = get_sequence(state)

        if intake.phase == "awaiting_target_retry" and sequence:
            error_text = intake.last_resolution_error or "Target molecule lookup failed."
            self.screen.add_system_message(
                "\n".join(
                    [
                        section_heading("Step 1: Intake Retry"),
                        "",
                        f"- **Sequence kept**: `{sequence}`",
                        f"- **Current target input**: `{intake.target_input or 'unknown'}`",
                        f"- **Issue**: {error_text}",
                        "- **Next input**: enter a corrected molecule name or SMILES.",
                        "- **Alternative**: paste a full intake brief to rerun extraction.",
                    ]
                ),
                "warning-text",
                markdown=True,
            )
            self.screen.set_input_placeholder(self._TARGET_RETRY_PLACEHOLDER)
        elif intake.phase == "awaiting_missing_target" and sequence:
            source_label = (
                f"PDB `{pdb_ctx.pdb_id}` chain `{pdb_ctx.selected_chain_id}`"
                if pdb_ctx.pdb_id and pdb_ctx.selected_chain_id
                else "the current intake context"
            )
            self.screen.add_system_message(
                "\n".join(
                    [
                        section_heading("Step 1: Missing Target Molecule"),
                        "",
                        f"- **Sequence kept** from {source_label}: `{sequence}`",
                        "- **Missing**: target small molecule",
                        "- **Next input**: provide the target molecule name or SMILES.",
                        "- **Alternative**: paste a new full intake brief to replace the current context.",
                    ]
                ),
                "warning-text",
                markdown=True,
            )
            self.screen.set_input_placeholder(self._MISSING_TARGET_PLACEHOLDER)
        elif intake.phase == "awaiting_pdb_selection" and pdb_ctx.chains:
            self.screen.add_system_message(
                "\n".join(
                    [
                        section_heading("Step 1: Review PDB Import"),
                        "",
                        f"- **PDB ID**: `{pdb_ctx.pdb_id or 'unknown'}`",
                        "- Multiple chain and/or ligand candidates were detected.",
                        "- Use the selection panel below, or paste a new full intake brief to restart.",
                    ]
                ),
                markdown=True,
            )
            self._pdb_helper.show_selection_panel()
            self.screen.set_input_placeholder(
                "Use the PDB selection panel, or paste a new intake brief."
            )
        elif intake.phase == "awaiting_pdb_review_gate":
            cat = pdb_ctx.review_category or "uncertain"
            tmatch = pdb_ctx.review_target_match or "unknown"
            conf = pdb_ctx.review_confidence or "medium"
            note = pdb_ctx.semantic_note or ""
            lines = [
                section_heading("Step 1: PDB Semantic Review"),
                "",
                f"- **PDB ID**: `{pdb_ctx.pdb_id or 'unknown'}`",
                f"- **Category**: `{cat}`",
                f"- **Target match**: `{tmatch}`",
                f"- **Confidence**: `{conf}`",
            ]
            if note:
                lines.append(f"- **Note**: {note}")
            lines.append("")
            lines.append("Use the panel below to proceed or go back.")
            self.screen.add_system_message(
                "\n".join(lines),
                markdown=True,
            )
            from aptgent.tui.widgets.structured_input import ActionMenuPanel as _AMP
            self.screen.add_structured_widget(
                _AMP(
                    step=Step.INTAKE,
                    title="PDB Review Confirmation",
                    choices=[
                        (
                            "proceed-pdb-review",
                            "Proceed anyway",
                            "Continue with this PDB structure despite the review finding.",
                        ),
                        (
                            "back-pdb-review",
                            "Back to intake",
                            "Return to intake and provide a different PDB or sequence.",
                        ),
                    ],
                    help_text="Use Up/Down to choose and Enter to confirm.",
                ),
            )
            self.screen.set_input_placeholder(
                "Use the panel above, or paste a new intake brief."
            )
        elif intake.phase == "awaiting_general_retry":
            error_text = intake.last_resolution_error or "The previous intake attempt could not be used."
            self.screen.add_system_message(
                "\n".join(
                    [
                        section_heading("Step 1: Intake Retry"),
                        "",
                        f"- **Issue**: {error_text}",
                        "- **Next input**: provide a valid PDB ID, or a sequence plus target molecule.",
                    ]
                ),
                "warning-text",
                markdown=True,
            )
            self.screen.set_input_placeholder(self._GENERAL_RETRY_PLACEHOLDER)
        else:
            self.screen.add_system_message(
                format_initial_intake_prompt(),
                markdown=True,
            )
            self.screen.set_input_placeholder(self._INITIAL_PLACEHOLDER)

        self.screen.set_input_enabled(True)

    def handle_user_input(self, text: str) -> None:
        text = text.strip()
        if not text:
            return

        state = self.screen.app.current_state
        phase = state.context.intake.phase

        if phase in {"awaiting_target_retry", "awaiting_missing_target"}:
            if looks_like_full_intake(text):
                self._start_full_extract(text)
                return
            self.run_worker(
                lambda: self._resolve_molecule_direct(text),
                activity="Resolving target molecule...",
            )
            return

        if phase == "awaiting_pdb_selection":
            if looks_like_full_intake(text):
                self._start_full_extract(text)
                return
            self.screen.add_system_message(
                "Use the PDB selection panel, or paste a new full intake brief.",
                "warning-text",
            )
            return

        if phase == "awaiting_pdb_review_gate":
            if looks_like_full_intake(text):
                self._start_full_extract(text)
                return
            self.screen.add_system_message(
                "Use the review panel above, or paste a new full intake brief.",
                "warning-text",
            )
            return

        self._start_full_extract(text)

    def handle_structured_input(self, data: dict) -> None:
        if data.get("action") != "confirm_pdb_selection":
            return
        chain_id = clean_text(data.get("chain_id"))
        ligand_key = clean_text(data.get("ligand_key"))
        self.run_worker(
            lambda: self._pdb_helper.apply_pdb_selection(chain_id, ligand_key),
            activity="Applying PDB selection...",
        )

    def handle_action(self, action: str) -> None:
        if action == "restart-pdb-selection":
            record_intake_context(
                self.screen.app.current_state,
                phase="awaiting_general_retry",
                last_resolution_error="PDB import was not confirmed.",
            )
            self.screen.advance_to_step(Step.INTAKE)
        elif action == "proceed-pdb-review":
            self.run_worker(
                lambda: self._pdb_helper.resume_after_review_gate(proceed=True),
                activity="Continuing PDB import...",
            )
        elif action == "back-pdb-review":
            self.run_worker(
                lambda: self._pdb_helper.resume_after_review_gate(proceed=False),
                activity="Returning to intake...",
            )

    def _start_full_extract(self, text: str) -> None:
        state = self.screen.app.current_state
        if state.context.intake.phase not in {"awaiting_target_retry", "awaiting_missing_target"}:
            state.context.intake.sequence = None
            state.context.intake.target_input = None
            state.context.intake.target_label = None
            state.target_molecule = None
            state.input_payload.pop("initial_sequence", None)
            state.input_payload.pop("target_molecule", None)
        record_intake_context(
            state,
            user_brief=text,
            phase="initial",
            clear_resolution_error=True,
        )
        state.input_payload["user_text"] = text
        self.run_worker(self._extract, activity="Extracting intake details...")

    def _extract(self) -> None:
        state = self.screen.app.current_state
        text = state.context.intake.user_brief or state.input_payload.get("user_text", "")

        try:
            skill = self.screen.app.create_intake_skill()
            result = run_llm_interaction(
                self.screen,
                display_stream=None,
                structured_call=lambda: validate_intake_result(skill.extract(text)),
            )
        except Exception as exc:
            self._report_error(f"LLM error: {exc}")
            return

        state.input_payload["llm_extracted"] = result

        seq = result.get("initial_sequence")
        pdb_id = result.get("pdb_id") or normalize_pdb_id(text)
        target_text = result.get("target_molecule")
        mod = result.get("modification_region")
        analogs = result.get("analogs", [])
        time_budget = result.get("time_budget_hours")
        proposed_sites_raw = result.get("proposed_sites", [])
        mutation_ratio = result.get("mutation_ratio")
        mixed_input_detected = bool(result.get("mixed_input_detected") or (pdb_id and (seq or target_text)))

        if mod:
            state.input_payload["modification_region"] = mod
        else:
            state.input_payload.pop("modification_region", None)
        if analogs:
            state.input_payload["analogs"] = analogs
        else:
            state.input_payload.pop("analogs", None)
        if time_budget is not None:
            state.time_budget = time_budget
        if seq:
            state.input_payload["initial_sequence"] = seq
        elif not pdb_id:
            state.input_payload.pop("initial_sequence", None)

        proposed_sites_0: list[int] = []
        if proposed_sites_raw:
            proposed_sites_0 = [s - 1 for s in proposed_sites_raw if isinstance(s, int) and s > 0]
            if seq:
                before = len(proposed_sites_0)
                proposed_sites_0 = [s for s in proposed_sites_0 if 0 <= s < len(seq)]
                if len(proposed_sites_0) < before:
                    state.context.intake.proposed_sites = proposed_sites_0
                    self._threadsafe(
                        self.screen.add_system_message,
                        f"Some proposed sites were out of range (sequence length {len(seq)}) and have been dropped.",
                        "warning-text",
                    )

        record_intake_context(
            state,
            user_brief=text,
            sequence=seq,
            target_text=target_text,
            modification_region=mod,
            analogs=analogs,
            proposed_sites=proposed_sites_0,
            time_budget_hours=time_budget,
            mutation_ratio=mutation_ratio,
            phase="initial",
            clear_resolution_error=True,
        )

        if pdb_id:
            record_pdb_intake_context(
                state,
                clear=True,
                pdb_id=pdb_id,
                input_mode="mixed" if mixed_input_detected else "pdb",
                mixed_input_detected=mixed_input_detected,
                user_sequence=seq,
                analysis_status="queued",
            )
            self.run_worker(
                lambda: self._pdb_helper.analyze_pdb_intake(
                    pdb_id=pdb_id,
                    user_sequence=seq,
                    user_target_text=target_text,
                    user_brief=text,
                    modification_region=mod,
                    analogs=analogs,
                    time_budget_hours=time_budget,
                ),
                activity="Analyzing PDB intake...",
            )
            return

        record_pdb_intake_context(state, clear=True)

        if not seq or not target_text:
            follow_up = (
                result.get("follow_up_question")
                or "Please provide the aptamer sequence and target molecule."
            )
            missing_parts: list[str] = []
            if not seq:
                missing_parts.append("sequence")
            if not target_text:
                missing_parts.append("target molecule")
            self._threadsafe(
                self.screen.add_system_message,
                f"Missing {', '.join(missing_parts)}. {follow_up}",
                "warning-text",
            )
            self._enable_input()
            self.screen.app.save_state()
            return

        self._resolve_and_complete(
            sequence=seq,
            target_text=target_text,
            user_brief=text,
            modification_region=mod,
            analogs=analogs,
            time_budget_hours=time_budget,
        )

    def _resolve_molecule_direct(self, text: str) -> None:
        state = self.screen.app.current_state
        resolved_text, resolved = self._resolve_target_text(text)
        if resolved is None or resolved.resolution_status != "resolved":
            self._activate_target_retry(
                text,
                _resolution_error_message(text, resolved),
            )
            return

        state.target_molecule = resolved
        self._complete_intake(
            sequence=get_sequence(state) or "",
            target_text=resolved_text,
            resolved=resolved,
            modification_region=state.input_payload.get("modification_region"),
            analogs=state.input_payload.get("analogs", []),
            time_budget_hours=getattr(state, "time_budget", None),
        )

    def _resolve_target_text(
        self,
        target_text: str,
    ) -> tuple[str, TargetMolecule | None]:
        return resolve_target_text(
            target_text,
            molecule_resolver=self.screen.app.molecule_resolver,
            intake_skill_factory=self.screen.app.create_intake_skill,
        )

    def _resolve_and_complete(
        self,
        *,
        sequence: str,
        target_text: str,
        user_brief: str | None,
        modification_region: str | None,
        analogs: list[str],
        time_budget_hours: int | None,
        source_label: str | None = None,
    ) -> None:
        state = self.screen.app.current_state
        resolved_text, resolved = self._resolve_target_text(target_text)
        if resolved is None or resolved.resolution_status != "resolved":
            self._activate_target_retry(
                target_text,
                _resolution_error_message(target_text, resolved, source="intake"),
                user_brief=user_brief,
                sequence=sequence,
                modification_region=modification_region,
                analogs=analogs,
                time_budget_hours=time_budget_hours,
            )
            return

        state.target_molecule = resolved
        self._complete_intake(
            sequence=sequence,
            target_text=resolved_text,
            resolved=resolved,
            modification_region=modification_region,
            analogs=analogs,
            time_budget_hours=time_budget_hours,
            user_brief=user_brief,
            source_label=source_label,
        )

    def _activate_target_retry(
        self,
        target_text: str,
        error_message: str,
        *,
        user_brief: str | None = None,
        sequence: str | None = None,
        modification_region: str | None = None,
        analogs: list[str] | None = None,
        time_budget_hours: int | None = None,
    ) -> None:
        state = self.screen.app.current_state
        intake = state.context.intake
        state.target_molecule = TargetMolecule(
            input_text=target_text,
            resolution_status="failed",
        )
        record_intake_context(
            state,
            user_brief=user_brief,
            sequence=sequence,
            target_text=target_text,
            modification_region=modification_region,
            analogs=analogs,
            time_budget_hours=time_budget_hours,
            phase="awaiting_target_retry",
            retry_count=intake.retry_count + 1,
            last_resolution_error=error_message,
            resolved_once=False,
        )
        self.screen.app.save_state()
        self._threadsafe(self.screen.advance_to_step, Step.INTAKE)

    def _activate_general_retry(self, error_message: str) -> None:
        state = self.screen.app.current_state
        record_intake_context(
            state,
            phase="awaiting_general_retry",
            last_resolution_error=error_message,
            resolved_once=False,
        )
        self.screen.app.save_state()
        self._threadsafe(self.screen.advance_to_step, Step.INTAKE)

    def _complete_intake(
        self,
        *,
        sequence: str,
        target_text: str,
        resolved: TargetMolecule,
        modification_region: str | None,
        analogs: list[str],
        time_budget_hours: int | None,
        user_brief: str | None = None,
        source_label: str | None = None,
    ) -> None:
        state = self.screen.app.current_state
        state.input_payload["initial_sequence"] = sequence
        state.input_payload["target_molecule"] = target_text
        if modification_region:
            state.input_payload["modification_region"] = modification_region
        if analogs:
            state.input_payload["analogs"] = analogs
        if time_budget_hours is not None:
            state.time_budget = time_budget_hours

        record_intake_context(
            state,
            user_brief=user_brief,
            sequence=sequence,
            target_text=target_text,
            resolved_target=resolved,
            modification_region=modification_region,
            analogs=analogs,
            time_budget_hours=time_budget_hours,
            phase="initial",
            clear_resolution_error=True,
            resolved_once=True,
        )

        if source_label:
            self._threadsafe(
                self.screen.add_tool_message,
                f"**Intake source**\n\n- Using `{source_label}` as the authoritative sequence source.",
                label="agent:intake",
            )

        confirmation = format_intake_confirmation(
            sequence=sequence,
            target_text=target_text,
            resolved=resolved,
            modification_region=modification_region,
            analogs=analogs,
            time_budget_hours=time_budget_hours,
        )
        self.screen.app.save_state()
        self._threadsafe(
            lambda: self.screen.add_system_message(
                confirmation,
                extra_class="",
                markdown=True,
            )
        )
        ns = next_primary_step(Step.INTAKE)
        if ns:
            self._threadsafe(self.screen.advance_to_step, ns)
