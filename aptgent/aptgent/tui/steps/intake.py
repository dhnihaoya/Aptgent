from __future__ import annotations

from aptgent.domain.enums import Step
from aptgent.domain.models import TargetMolecule
from aptgent.llm.skills import IntakeSkill
from aptgent.tui.steps.base import StepHandler
from aptgent.tui.steps.common import (
    clean_text,
    format_intake_confirmation,
    next_step,
    run_llm_interaction,
    validate_intake_result,
)
from aptgent.workflow.context import get_sequence, record_intake_context


class IntakeHandler(StepHandler):
    def enter(self) -> None:
        self.screen.add_system_message(
            "Step 1: Intake\n"
            "Describe your aptamer design task. Include the sequence, "
            "target molecule (name or SMILES), and any preferences."
        )
        self.screen.set_input_enabled(True)
        self.screen.set_input_placeholder(
            "e.g. Design an aptamer for theophylline, sequence: GGGAAACCC..."
        )

    def handle_user_input(self, text: str) -> None:
        state = self.screen.app.current_state
        record_intake_context(state, user_brief=text.strip())
        seq = get_sequence(state) or ""
        target = state.target_molecule
        if seq and target and target.resolution_status != "resolved":
            self.run_worker(
                lambda: self._resolve_molecule_direct(text.strip()),
                activity="Resolving target molecule...",
            )
            return
        self.run_worker(self._extract, activity="Extracting intake details...")

    def _resolve_molecule_direct(self, text: str) -> None:
        state = self.screen.app.current_state
        resolved = self.screen.app.molecule_resolver.resolve(text)
        if resolved.resolution_status == "resolved":
            state.target_molecule = resolved
            record_intake_context(
                state,
                target_text=text,
                resolved_target=resolved,
                sequence=get_sequence(state),
                modification_region=state.input_payload.get("modification_region"),
                analogs=state.input_payload.get("analogs", []),
                time_budget_hours=getattr(state, "time_budget", None),
            )
            self.screen.app.save_state()
            confirmation = format_intake_confirmation(
                sequence=get_sequence(state) or "",
                target_text=text,
                resolved=resolved,
                modification_region=state.input_payload.get("modification_region"),
                analogs=state.input_payload.get("analogs", []),
                time_budget_hours=getattr(state, "time_budget", None),
            )
            self.screen.app.call_from_thread(
                self.screen.add_system_message, confirmation
            )
            ns = next_step(Step.INTAKE)
            if ns:
                self.screen.app.call_from_thread(self.screen.advance_to_step, ns)
        else:
            self.screen.app.call_from_thread(
                self.screen.add_system_message,
                f"Could not resolve '{text}' either. "
                "Please provide a valid SMILES string.",
                "warning-text",
            )
            self.screen.app.call_from_thread(self.screen.set_input_enabled, True)

    def _extract(self) -> None:
        state = self.screen.app.current_state
        text = state.context.intake.user_brief or state.input_payload.get("user_text", "")

        try:
            skill = IntakeSkill()
            result = run_llm_interaction(
                self.screen,
                display_stream=None,
                structured_call=lambda: validate_intake_result(skill.extract(text)),
            )
        except Exception as exc:
            self.screen.app.call_from_thread(
                self.screen.add_system_message, f"LLM error: {exc}", "error-text"
            )
            self.screen.app.call_from_thread(self.screen.set_input_enabled, True)
            return

        state.input_payload["llm_extracted"] = result

        seq = result.get("initial_sequence")
        target_text = result.get("target_molecule")
        if not seq or not target_text:
            follow_up = result.get("follow_up_question") or "Please provide the aptamer sequence and target molecule."
            missing_parts: list[str] = []
            if not seq:
                missing_parts.append("sequence")
            if not target_text:
                missing_parts.append("target molecule")
            self.screen.app.call_from_thread(
                self.screen.add_system_message,
                f"Missing {', '.join(missing_parts)}. {follow_up}",
                "warning-text",
            )
            self.screen.app.call_from_thread(self.screen.set_input_enabled, True)
            self.screen.app.save_state()
            return

        state.input_payload["initial_sequence"] = seq
        analogs = result.get("analogs", [])

        resolved = self.screen.app.molecule_resolver.resolve(target_text)
        if resolved.resolution_status != "resolved" and any(
            "\u4e00" <= ch <= "\u9fff" for ch in target_text
        ):
            try:
                translate_prompt = (
                    "Translate the following molecule name to its standard English common name. "
                    'Return ONLY a JSON object: {"english_name": "<english name>"}.'
                )
                translated = skill.client.chat_json(translate_prompt, target_text)
                english_name = None
                if isinstance(translated, dict):
                    english_name = clean_text(
                        translated.get("english_name")
                        or translated.get("name")
                        or translated.get("translation")
                    )
                    if english_name is None and translated:
                        english_name = clean_text(next(iter(translated.values())))
                elif isinstance(translated, str):
                    english_name = clean_text(translated)
                if english_name:
                    resolved = self.screen.app.molecule_resolver.resolve(english_name)
                    if resolved.resolution_status == "resolved":
                        target_text = english_name
            except Exception:
                pass
        if resolved.resolution_status == "resolved":
            state.target_molecule = resolved
        else:
            state.target_molecule = TargetMolecule(input_text=target_text)
            self.screen.app.save_state()
            self.screen.app.call_from_thread(
                self.screen.add_system_message,
                f"Could not resolve molecule '{target_text}'. "
                "Please provide a valid SMILES string or molecule name directly.",
                "warning-text",
            )
            self.screen.app.call_from_thread(self.screen.set_input_enabled, True)
            self.screen.app.call_from_thread(
                self.screen.set_input_placeholder,
                "Enter SMILES (e.g. Cn1c2c(c(=O)n(c1=O)C)[nH]cn2) or molecule name",
            )
            return

        mod = result.get("modification_region")
        if mod:
            state.input_payload["modification_region"] = mod
        if analogs:
            state.input_payload["analogs"] = analogs
        time_budget = result.get("time_budget_hours")
        if time_budget is not None:
            state.time_budget = time_budget

        record_intake_context(
            state,
            user_brief=text,
            sequence=seq,
            target_text=target_text,
            resolved_target=state.target_molecule,
            modification_region=mod,
            analogs=analogs,
            time_budget_hours=time_budget,
        )

        confirmation = format_intake_confirmation(
            sequence=seq,
            target_text=target_text,
            resolved=state.target_molecule,
            modification_region=mod,
            analogs=analogs,
            time_budget_hours=time_budget,
        )
        self.screen.app.save_state()
        self.screen.app.call_from_thread(
            self.screen.add_system_message, confirmation
        )
        ns = next_step(Step.INTAKE)
        if ns:
            self.screen.app.call_from_thread(self.screen.advance_to_step, ns)
