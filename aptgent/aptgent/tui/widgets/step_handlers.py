from __future__ import annotations

import itertools
from pathlib import Path
from typing import Any, Callable

from aptgent.adapters.docking import HardwareProbeAdapter
from aptgent.domain.enums import Step
from aptgent.domain.models import (
    CandidateSequence,
    DockingPlan,
    FinalRecommendation,
    Mutation,
    SpecificityResult,
    TargetMolecule,
)
from aptgent.llm.skills import (
    AnalogSuggestionSkill,
    DockingPlannerSkill,
    IntakeSkill,
    ReportSkill,
    SiteProposalSkill,
)
from aptgent.workflow.engine import TRANSITIONS
from aptgent.tui.widgets.structured_input import (
    CheckboxPanel,
    DockingParamPanel,
    SpecificityPanel,
)


class StepHandler:
    """Base class for per-step handlers."""

    def __init__(self, screen: Any) -> None:
        self.screen = screen

    def enter(self) -> None:
        """Called when the step becomes active."""
        ...

    def handle_user_input(self, text: str) -> None:
        """Called when the user submits free-text input."""
        ...

    def handle_structured_input(self, data: dict) -> None:
        """Called when a structured panel submits data."""
        ...

    def handle_action(self, action: str) -> None:
        """Called when a structured panel requests an action."""
        ...


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _next_step(step: Step) -> Step | None:
    targets = TRANSITIONS.get(step, [])
    return targets[0] if targets else None


def _clean_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _normalize_sequence(value: Any) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    sequence = "".join(ch for ch in text.upper() if not ch.isspace())
    allowed = {"A", "C", "G", "T", "U"}
    if not sequence or any(ch not in allowed for ch in sequence):
        return None
    return sequence


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip():
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _coerce_int_list(
    values: Any,
    *,
    min_value: int | None = None,
    max_value: int | None = None,
) -> list[int]:
    if not isinstance(values, list):
        return []
    result: list[int] = []
    seen: set[int] = set()
    for item in values:
        value = _coerce_int(item)
        if value is None:
            continue
        if min_value is not None and value < min_value:
            continue
        if max_value is not None and value > max_value:
            continue
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _run_llm_interaction(
    screen: Any,
    *,
    display_stream: Callable[[], Any] | None,
    structured_call: Callable[[], Any],
) -> dict[str, Any]:
    from textual.worker import get_current_worker

    worker = get_current_worker()
    if worker.is_cancelled:
        return {}

    bubble = None
    display_error: Exception | None = None

    if display_stream is not None:
        def _make_bubble() -> None:
            nonlocal bubble
            bubble = screen.add_streaming_message()

        screen.app.call_from_thread(_make_bubble)
        try:
            for chunk in display_stream():
                if worker.is_cancelled:
                    return {}
                screen.app.call_from_thread(bubble.append_text, chunk)
        except Exception as exc:
            display_error = exc
        finally:
            if bubble:
                screen.app.call_from_thread(bubble.finalize)

    if worker.is_cancelled:
        return {}

    result = structured_call()
    if not isinstance(result, dict):
        raise RuntimeError("LLM returned a non-object response.")

    if display_error is not None:
        screen.app.call_from_thread(
            screen.add_system_message,
            f"LLM explanation unavailable; using structured fallback. {display_error}",
            "warning-text",
        )

    return result


def _validate_intake_result(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise RuntimeError("Invalid intake response.")
    missing_fields = []
    for item in result.get("missing_fields", []):
        text = _clean_text(item)
        if text:
            missing_fields.append(text)
    return {
        "initial_sequence": _normalize_sequence(result.get("initial_sequence")),
        "target_molecule": _clean_text(result.get("target_molecule")),
        "modification_region": _clean_text(result.get("modification_region")),
        "analogs": [
            text for text in (_clean_text(item) for item in result.get("analogs", []))
            if text
        ] if isinstance(result.get("analogs"), list) else [],
        "time_budget_hours": _coerce_int(result.get("time_budget_hours")),
        "missing_fields": missing_fields,
        "follow_up_question": _clean_text(result.get("follow_up_question")),
    }


def _validate_site_proposal_result(result: Any, sequence_length: int) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise RuntimeError("Invalid site proposal response.")
    return {
        "proposed_sites": _coerce_int_list(
            result.get("proposed_sites"),
            min_value=0,
            max_value=max(sequence_length - 1, 0),
        ),
        "reasoning": _clean_text(result.get("reasoning")) or "Suggested from the current secondary-structure context.",
        "confidence": (_clean_text(result.get("confidence")) or "unknown").lower(),
    }


def _validate_analog_suggestion_result(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise RuntimeError("Invalid analog suggestion response.")
    analogs: list[dict[str, str | None]] = []
    raw_analogs = result.get("analogs", [])
    if isinstance(raw_analogs, list):
        for raw in raw_analogs:
            if not isinstance(raw, dict):
                continue
            name = _clean_text(raw.get("name"))
            if not name:
                continue
            analogs.append(
                {
                    "name": name,
                    "smiles": _clean_text(raw.get("smiles")),
                    "reason": _clean_text(raw.get("reason")),
                }
            )
    return {
        "analogs": analogs,
        "note": _clean_text(result.get("note")),
    }


def _default_top_k(
    candidate_count: int,
    machine_profile: dict[str, Any],
    time_budget_hours: int | None,
) -> int:
    if candidate_count <= 0:
        return 0
    cpu_count = _coerce_int(machine_profile.get("cpu_count")) or 1
    budget_hours = max(time_budget_hours or 1, 1)
    rough_capacity = cpu_count * budget_hours * 4
    return max(1, min(candidate_count, rough_capacity))


def _validate_docking_recommendation_result(
    result: Any,
    *,
    candidate_count: int,
    machine_profile: dict[str, Any],
    time_budget_hours: int | None,
) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise RuntimeError("Invalid docking recommendation response.")
    top_k = _coerce_int(result.get("recommended_top_k"))
    if top_k is None or top_k <= 0:
        top_k = _default_top_k(candidate_count, machine_profile, time_budget_hours)
    top_k = min(top_k, candidate_count)
    reason = _clean_text(result.get("reason")) or "Using a conservative docking batch size based on available resources."
    return {
        "recommended_top_k": top_k,
        "reason": reason,
    }


def _validate_report_summary(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise RuntimeError("Invalid report summary response.")
    candidate_notes = result.get("candidate_notes")
    if not isinstance(candidate_notes, dict):
        candidate_notes = {}
    return {
        "summary": _clean_text(result.get("summary")) or "",
        "candidate_notes": candidate_notes,
    }


# ---------------------------------------------------------------------------
# Step 1: Intake
# ---------------------------------------------------------------------------

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
        self.screen.set_input_enabled(False)
        self.screen.run_worker(self._extract, exclusive=True, thread=True)

    def _extract(self) -> None:
        state = self.screen.app.current_state
        text = state.input_payload.get("user_text", "")

        try:
            skill = IntakeSkill()
            result = _run_llm_interaction(
                self.screen,
                display_stream=lambda: skill.explain_extract_stream(text),
                structured_call=lambda: _validate_intake_result(skill.extract(text)),
            )
        except Exception as e:
            self.screen.app.call_from_thread(
                self.screen.add_system_message, f"LLM error: {e}", "error-text"
            )
            self.screen.app.call_from_thread(self.screen.set_input_enabled, True)
            return

        state.input_payload["user_text"] = text
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
        msg_parts = [f"Sequence: {seq}"]

        resolved = self.screen.app.molecule_resolver.resolve(target_text)
        # Fallback: if resolution fails and name looks like CJK, translate via LLM
        if resolved.resolution_status != "resolved" and any(
            "\u4e00" <= ch <= "\u9fff" for ch in target_text
        ):
            try:
                translate_prompt = (
                    "Translate the following molecule name to its standard English common name. "
                    'Return ONLY a JSON object: {"english_name": "<english name>"}.'
                )
                translated = skill.client.chat_json(
                    translate_prompt, target_text
                )
                english_name = None
                if isinstance(translated, dict):
                    english_name = _clean_text(
                        translated.get("english_name")
                        or translated.get("name")
                        or translated.get("translation")
                    )
                    if english_name is None and translated:
                        english_name = _clean_text(next(iter(translated.values())))
                elif isinstance(translated, str):
                    english_name = _clean_text(translated)
                if english_name:
                    resolved = self.screen.app.molecule_resolver.resolve(english_name)
                    if resolved.resolution_status == "resolved":
                        target_text = english_name
            except Exception:
                pass
        if resolved.resolution_status == "resolved":
            state.target_molecule = resolved
            msg_parts.append(f"Target: {resolved.resolved_name or target_text} ({resolved.smiles})")
        else:
            state.target_molecule = TargetMolecule(input_text=target_text)
            msg_parts.append(f"Target: {target_text} (resolution failed)")

        mod = result.get("modification_region")
        if mod:
            state.input_payload["modification_region"] = mod
        time_budget = result.get("time_budget_hours")
        if time_budget is not None:
            state.time_budget = time_budget

        self.screen.app.save_state()
        self.screen.app.call_from_thread(
            self.screen.add_system_message, "\n".join(msg_parts)
        )
        ns = _next_step(Step.INTAKE)
        if ns:
            self.screen.app.call_from_thread(self.screen.advance_to_step, ns)


# ---------------------------------------------------------------------------
# Step 2: Secondary Structure
# ---------------------------------------------------------------------------

class StructureHandler(StepHandler):
    def enter(self) -> None:
        state = self.screen.app.current_state
        seq = state.input_payload.get("initial_sequence", "")
        if not seq:
            self.screen.add_system_message("Error: no sequence available.", "error-text")
            return
        self.screen.add_system_message(f"Running RNAfold on: {seq}")
        self.screen.set_input_enabled(False)
        self.screen.run_worker(self._run_fold, exclusive=True, thread=True)

    def _run_fold(self) -> None:
        state = self.screen.app.current_state
        seq = state.input_payload.get("initial_sequence", "")
        try:
            struct = self.screen.app.rna_fold_adapter.fold(seq)
            state.secondary_structure = struct
            self.screen.app.save_state()
            result_text = (
                f"Sequence: {struct.sequence}\n"
                f"Dot-bracket: {struct.dot_bracket}\n"
                f"MFE: {struct.mfe} kcal/mol"
            )
            self.screen.app.call_from_thread(self.screen.add_system_message, result_text)
            ns = _next_step(Step.SECONDARY_STRUCTURE)
            if ns:
                self.screen.app.call_from_thread(self.screen.advance_to_step, ns)
        except Exception as e:
            self.screen.app.call_from_thread(
                self.screen.add_system_message, f"RNAfold error: {e}", "error-text"
            )


# ---------------------------------------------------------------------------
# Step 3: Site Proposal
# ---------------------------------------------------------------------------

class SiteProposalHandler(StepHandler):
    def enter(self) -> None:
        state = self.screen.app.current_state
        seq = state.input_payload.get("initial_sequence", "")
        struct = state.secondary_structure

        if struct is None:
            self.screen.add_system_message(
                "No secondary structure available. Skipping site proposal.",
                "warning-text",
            )
            ns = _next_step(Step.SITE_PROPOSAL)
            if ns:
                self.screen.advance_to_step(ns)
            return

        self.screen.set_input_enabled(False)
        self.screen.run_worker(self._propose, exclusive=True, thread=True)

    def _propose(self) -> None:
        state = self.screen.app.current_state
        seq = state.input_payload.get("initial_sequence", "")
        struct = state.secondary_structure

        try:
            skill = SiteProposalSkill()
            result = _run_llm_interaction(
                self.screen,
                display_stream=lambda: skill.explain_propose_stream(seq, struct),
                structured_call=lambda: _validate_site_proposal_result(
                    skill.propose(seq, struct),
                    len(seq),
                ),
            )
        except Exception as e:
            self.screen.app.call_from_thread(
                self.screen.add_system_message, f"LLM error: {e}", "error-text"
            )
            self.screen.app.call_from_thread(self.screen.set_input_enabled, True)
            return

        sites = result.get("proposed_sites", [])
        reasoning = result.get("reasoning", "")
        self._proposed_sites = sites

        msg = f"Suggested sites: {sites}\nReasoning: {reasoning}"
        self.screen.app.call_from_thread(self.screen.add_system_message, msg)

        # Mount checkbox panel
        panel = CheckboxPanel(seq, sites)
        self.screen.app.call_from_thread(self.screen.add_structured_widget, panel)
        self.screen.app.call_from_thread(
            self.screen.set_input_placeholder,
            "Type positions (e.g. 3,7,12) or 'use suggestions'",
        )
        self.screen.app.call_from_thread(self.screen.set_input_enabled, True)

    def handle_user_input(self, text: str) -> None:
        state = self.screen.app.current_state
        seq = state.input_payload.get("initial_sequence", "")
        text_lower = text.strip().lower()

        if text_lower in ("use suggestions", "confirm", "accept", "ok"):
            sites = getattr(self, "_proposed_sites", [])
        else:
            # Try to parse as comma-separated integers
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

    def _confirm_sites(self, sites: list[int]) -> None:
        state = self.screen.app.current_state
        state.confirmed_mutation_sites = sites
        self.screen.app.save_state()
        self.screen.add_system_message(f"Confirmed mutation sites: {sites}")
        ns = _next_step(Step.SITE_PROPOSAL)
        if ns:
            self.screen.advance_to_step(ns)


# ---------------------------------------------------------------------------
# Step 4: Candidate Enumeration
# ---------------------------------------------------------------------------

class EnumerationHandler(StepHandler):
    def enter(self) -> None:
        state = self.screen.app.current_state
        seq: str = state.input_payload.get("initial_sequence", "")
        sites = state.confirmed_mutation_sites
        max_candidates = self.screen.app.config.get("enumeration", {}).get("max_candidates", 5000)

        if not sites:
            self.screen.add_system_message(
                "No mutation sites selected. Please go back.", "error-text"
            )
            return

        total = 4 ** len(sites)
        if total > max_candidates:
            self.screen.add_system_message(
                f"Too many candidates ({total} > {max_candidates}). "
                "Reduce mutation sites or increase threshold.",
                "error-text",
            )
            return

        self.screen.set_input_enabled(False)

        bases = ["A", "T", "G", "C"]
        candidates: list[CandidateSequence] = []
        for combo in itertools.product(bases, repeat=len(sites)):
            muts: list[Mutation] = []
            new_seq = list(seq)
            for idx, base in zip(sites, combo):
                muts.append(Mutation(position=idx, original=seq[idx], mutated=base))
                new_seq[idx] = base
            cand_seq = "".join(new_seq)
            edit_ratio = len(muts) / len(seq)
            candidates.append(
                CandidateSequence(
                    sequence=cand_seq,
                    mutations=muts,
                    edit_ratio=edit_ratio,
                    candidate_id=f"cand_{len(candidates)}",
                )
            )

        state.candidates = candidates
        self.screen.app.save_state()

        msg = f"Generated {len(candidates)} candidates from {len(sites)} mutation sites."
        # Show first few
        preview_lines = []
        for c in candidates[:5]:
            mut_str = ", ".join(f"{m.position}:{m.original}>{m.mutated}" for m in c.mutations)
            preview_lines.append(f"  {c.candidate_id} | {c.sequence[:40]}... | {mut_str}")
        if len(candidates) > 5:
            preview_lines.append(f"  ... and {len(candidates) - 5} more")
        msg += "\n" + "\n".join(preview_lines)

        self.screen.add_system_message(msg)
        ns = _next_step(Step.CANDIDATE_ENUMERATION)
        if ns:
            self.screen.advance_to_step(ns)


# ---------------------------------------------------------------------------
# Step 5: Primary Scoring
# ---------------------------------------------------------------------------

class ScoringHandler(StepHandler):
    def enter(self) -> None:
        state = self.screen.app.current_state
        candidates = state.candidates
        target = state.target_molecule

        if not candidates:
            self.screen.add_system_message("No candidates available.", "error-text")
            return
        if not target or not target.smiles:
            self.screen.add_system_message(
                "Target molecule missing. Cannot score.", "error-text"
            )
            return

        self.screen.add_system_message(
            f"Running ensemble prediction on {len(candidates)} candidates..."
        )
        self.screen.set_input_enabled(False)
        self.screen.run_worker(self._score, exclusive=True, thread=True)

    def _score(self) -> None:
        state = self.screen.app.current_state
        candidates = state.candidates
        target = state.target_molecule

        try:
            results = self.screen.app.prediction_adapter.predict_batch(candidates, target)
            state.predictions = results
            self.screen.app.save_state()

            # Format results
            ens_preds = [p for p in results if p.model_name == "ensemble"]
            sorted_preds = sorted(ens_preds, key=lambda x: x.probability or 0.0, reverse=True)

            lines = [f"Scored {len(sorted_preds)} candidates (ensemble):"]
            for p in sorted_preds[:10]:
                label_str = "Binding" if p.label == 1 else "Non-binding"
                lines.append(f"  {p.candidate_id}: {label_str} (P={p.probability:.4f})")
            if len(sorted_preds) > 10:
                lines.append(f"  ... and {len(sorted_preds) - 10} more")

            self.screen.app.call_from_thread(self.screen.add_system_message, "\n".join(lines))
            ns = _next_step(Step.PRIMARY_SCORING)
            if ns:
                self.screen.app.call_from_thread(self.screen.advance_to_step, ns)
        except Exception as e:
            self.screen.app.call_from_thread(
                self.screen.add_system_message, f"Scoring failed: {e}", "error-text"
            )


# ---------------------------------------------------------------------------
# Step 6: Specificity Filter
# ---------------------------------------------------------------------------

class SpecificityHandler(StepHandler):
    def enter(self) -> None:
        self.screen.add_system_message(
            "Step 6: Specificity Filter\n"
            "You can provide analog molecules, ask the LLM to suggest them, or skip this step."
        )
        panel = SpecificityPanel(
            target_name=self.screen.app.current_state.target_molecule.input_text if self.screen.app.current_state.target_molecule else ""
        )
        self.screen.add_structured_widget(panel)
        self.screen.set_input_enabled(True)
        self.screen.set_input_placeholder("Type 'skip', 'suggest', or analog names (comma-separated)")

    def handle_user_input(self, text: str) -> None:
        text_lower = text.strip().lower()
        if text_lower == "skip":
            self._skip()
        elif text_lower == "suggest":
            self._suggest()
        else:
            # Treat as analog input
            self._run_filter(text, echo_user=False)

    def handle_structured_input(self, data: dict) -> None:
        action = data.get("action", "run")
        if action == "skip":
            self._skip()
        elif action == "suggest":
            self._suggest()
        else:
            analogs_text = data.get("analogs_text", "")
            self._run_filter(analogs_text, echo_user=bool(analogs_text.strip()))

    def handle_action(self, action: str) -> None:
        if action == "suggest":
            self._suggest()

    def _suggest(self) -> None:
        self.screen.set_input_enabled(False)
        self.screen.run_worker(self._suggest_worker, exclusive=True, thread=True)

    def _suggest_worker(self) -> None:
        target = self.screen.app.current_state.target_molecule

        try:
            skill = AnalogSuggestionSkill()
            result = _run_llm_interaction(
                self.screen,
                display_stream=lambda: skill.explain_suggest_stream(target),
                structured_call=lambda: _validate_analog_suggestion_result(skill.suggest(target)),
            )
            analogs = result.get("analogs", [])
            names = ", ".join(a.get("name", "") for a in analogs if a.get("name"))
            self.screen.app.call_from_thread(
                self.screen.add_system_message,
                f"Loaded suggested analogs into the input field: {names}" if names else "No analog suggestions were returned.",
            )
            # Update the panel input
            self.screen.app.call_from_thread(self._update_analog_input, names)
            self.screen.app.call_from_thread(self.screen.set_input_enabled, True)
        except Exception as e:
            self.screen.app.call_from_thread(
                self.screen.add_system_message, f"Suggestion failed: {e}", "error-text"
            )
            self.screen.app.call_from_thread(self.screen.set_input_enabled, True)

    def _update_analog_input(self, names: str) -> None:
        try:
            panel = self.screen.query_one(SpecificityPanel)
            panel.query_one("#analog-input").value = names
        except Exception:
            pass

    def _run_filter(self, analogs_text: str, *, echo_user: bool) -> None:
        if echo_user:
            self.screen.add_user_message(f"Filter with: {analogs_text}")
        self.screen.set_input_enabled(False)

        state = self.screen.app.current_state
        target = state.target_molecule
        candidates = state.candidates

        if not analogs_text.strip():
            self.screen.add_system_message("No analogs provided. Nothing to filter.")
            self.screen.set_input_enabled(True)
            return

        # Parse analogs
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

        self.screen.add_system_message(
            f"Running cross-prediction on {len(candidates)} candidates x {len(analogs)} analogs..."
        )
        self.screen.run_worker(
            lambda: self._filter_worker(candidates, target, analogs),
            exclusive=True,
            thread=True,
        )

    def _filter_worker(self, candidates, target, analogs) -> None:
        try:
            results_by_target = self.screen.app.prediction_adapter.predict_batch_for_targets(
                candidates, [target] + analogs
            )
            primary_results = results_by_target.get(target.smiles, [])
            specificity_results: list[SpecificityResult] = []
            kept_count = 0

            for cand in candidates:
                cand_id = cand.candidate_id or ""
                failed: list[str] = []
                for analog in analogs:
                    if not analog.smiles:
                        continue
                    analog_preds = results_by_target.get(analog.smiles, [])
                    ap = next((p for p in analog_preds if p.candidate_id == cand_id), None)
                    if ap and ap.label == 1:
                        failed.append(analog.input_text)

                status_str = "removed" if failed else "kept"
                if not failed:
                    kept_count += 1
                specificity_results.append(
                    SpecificityResult(
                        candidate_id=cand_id,
                        status=status_str,
                        failed_analogs=failed,
                    )
                )

            state = self.screen.app.current_state
            state.specificity_results = specificity_results
            self.screen.app.save_state()

            msg = f"Filter complete. {kept_count}/{len(candidates)} candidates kept."
            if kept_count < len(candidates):
                removed = [r.candidate_id for r in specificity_results if r.status == "removed"]
                msg += f"\nRemoved: {', '.join(removed[:10])}"

            self.screen.app.call_from_thread(self.screen.add_system_message, msg)
            ns = _next_step(Step.SPECIFICITY_FILTER)
            if ns:
                self.screen.app.call_from_thread(self.screen.advance_to_step, ns)
        except Exception as e:
            self.screen.app.call_from_thread(
                self.screen.add_system_message, f"Filter failed: {e}", "error-text"
            )
            self.screen.app.call_from_thread(self.screen.set_input_enabled, True)

    def _skip(self) -> None:
        state = self.screen.app.current_state
        state.specificity_results = [
            SpecificityResult(candidate_id=c.candidate_id or "", status="skipped")
            for c in state.candidates
        ]
        self.screen.app.save_state()
        self.screen.add_system_message("Specificity filter skipped.")
        ns = _next_step(Step.SPECIFICITY_FILTER)
        if ns:
            self.screen.advance_to_step(ns)


# ---------------------------------------------------------------------------
# Step 7: Docking Selection
# ---------------------------------------------------------------------------

class DockingSelectionHandler(StepHandler):
    def enter(self) -> None:
        state = self.screen.app.current_state

        self.screen.add_system_message(
            f"Step 7: Docking Selection\n"
            f"{len(state.candidates)} candidates available for docking."
        )
        panel = DockingParamPanel()
        self.screen.add_structured_widget(panel)
        self.screen.set_input_enabled(True)
        self.screen.set_input_placeholder(
            "Configure docking params above, or type 'skip docking'"
        )

    def handle_user_input(self, text: str) -> None:
        text_lower = text.strip().lower()
        if "skip" in text_lower:
            # Skip to spatial rank
            state = self.screen.app.current_state
            state.docking_plan = DockingPlan(recommended_top_k=0)
            self.screen.app.save_state()
            self.screen.add_system_message("Docking skipped.")
            ns = _next_step(Step.DOCKING_SELECTION)
            if ns:
                self.screen.advance_to_step(ns)

    def handle_structured_input(self, data: dict) -> None:
        state = self.screen.app.current_state
        top_k = data.get("top_k", 0)
        candidate_count = len(state.candidates)

        if top_k <= 0:
            self.screen.add_system_message("Please enter a valid top-k > 0.", "warning-text")
            return
        if candidate_count and top_k > candidate_count:
            top_k = candidate_count

        profile = HardwareProbeAdapter().probe()
        state.docking_plan = DockingPlan(
            machine_profile=profile,
            time_budget=data.get("time_budget"),
            recommended_top_k=top_k,
            receptor_path=data.get("receptor_path"),
            grid_center=data.get("grid_center"),
            grid_size=data.get("grid_size"),
        )
        self.screen.app.save_state()
        self.screen.add_system_message(
            f"Docking plan: top-{top_k} candidates, "
            f"receptor={data.get('receptor_path', 'N/A')}"
        )
        ns = _next_step(Step.DOCKING_SELECTION)
        if ns:
            self.screen.advance_to_step(ns)

    def handle_action(self, action: str) -> None:
        if action.startswith("recommend:"):
            budget_str = action.split(":", 1)[1]
            time_budget = int(budget_str) if budget_str.isdigit() else None
            self.screen.set_input_enabled(False)
            self.screen.run_worker(
                lambda: self._recommend_worker(time_budget),
                exclusive=True,
                thread=True,
            )

    def _recommend_worker(self, time_budget: int | None) -> None:
        state = self.screen.app.current_state
        profile = HardwareProbeAdapter().probe()

        try:
            skill = DockingPlannerSkill()
            result = _run_llm_interaction(
                self.screen,
                display_stream=lambda: skill.explain_plan_stream(
                    candidate_count=len(state.candidates),
                    machine_profile=profile,
                    time_budget_hours=time_budget,
                ),
                structured_call=lambda: _validate_docking_recommendation_result(
                    skill.plan(
                        candidate_count=len(state.candidates),
                        machine_profile=profile,
                        time_budget_hours=time_budget,
                    ),
                    candidate_count=len(state.candidates),
                    machine_profile=profile,
                    time_budget_hours=time_budget,
                ),
            )
            top_k = result.get("recommended_top_k", 0)
            reason = result.get("reason", "")
            self.screen.app.call_from_thread(
                self.screen.add_system_message,
                f"Recommended docking batch size set to top {top_k}. {reason}",
            )
            self.screen.app.call_from_thread(self._update_panel, top_k, reason)
        except Exception as e:
            self.screen.app.call_from_thread(
                self.screen.add_system_message, f"Recommendation failed: {e}", "error-text"
            )
        finally:
            self.screen.app.call_from_thread(self.screen.set_input_enabled, True)

    def _update_panel(self, top_k: int, reason: str) -> None:
        try:
            panel = self.screen.query_one(DockingParamPanel)
            panel.set_recommendation(top_k, reason)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Step 8: Docking Run
# ---------------------------------------------------------------------------

class DockingRunHandler(StepHandler):
    def enter(self) -> None:
        state = self.screen.app.current_state
        plan = state.docking_plan
        target = state.target_molecule

        if not plan or plan.recommended_top_k <= 0:
            self.screen.add_system_message("Docking skipped (no plan or top-k = 0).")
            ns = _next_step(Step.DOCKING_RUN)
            if ns:
                self.screen.advance_to_step(ns)
            return

        if not target or not target.smiles:
            self.screen.add_system_message("Target molecule missing.", "error-text")
            return

        if not plan.receptor_path or not Path(plan.receptor_path).exists():
            self.screen.add_system_message(
                f"Receptor file not found: {plan.receptor_path}",
                "error-text",
            )
            return

        if not plan.grid_center or not plan.grid_size:
            self.screen.add_system_message("Grid box parameters not set.", "error-text")
            return

        # Select top-k candidates
        ens_preds = [p for p in state.predictions if p.model_name == "ensemble"]
        sorted_preds = sorted(ens_preds, key=lambda x: x.probability or 0.0, reverse=True)
        top_k = plan.recommended_top_k
        top_cand_ids = {p.candidate_id for p in sorted_preds[:top_k]}
        top_candidates = [c for c in state.candidates if c.candidate_id in top_cand_ids]

        self.screen.add_system_message(
            f"Running Vina docking on {len(top_candidates)} candidates..."
        )
        self.screen.set_input_enabled(False)
        self.screen.run_worker(
            lambda: self._dock_worker(top_candidates, target),
            exclusive=True,
            thread=True,
        )

    def _dock_worker(self, candidates, target) -> None:
        state = self.screen.app.current_state
        plan = state.docking_plan
        try:
            work_dir = Path(state.run_id) / "docking"
            results = self.screen.app.vina_adapter.run_batch(
                candidates=candidates,
                target=target,
                receptor_pdbqt=plan.receptor_path,
                center=plan.grid_center,
                size=plan.grid_size,
                work_dir=work_dir,
            )
            state.docking_results = results
            self.screen.app.save_state()

            lines = [f"Docking complete. {len(results)} results:"]
            sorted_results = sorted(results, key=lambda r: r.docking_score or 0.0)
            for r in sorted_results[:10]:
                score_str = f"{r.docking_score:.3f}" if r.docking_score is not None else "N/A"
                lines.append(f"  {r.candidate_id}: {score_str} ({r.status})")
            if len(sorted_results) > 10:
                lines.append(f"  ... and {len(sorted_results) - 10} more")

            self.screen.app.call_from_thread(self.screen.add_system_message, "\n".join(lines))
            ns = _next_step(Step.DOCKING_RUN)
            if ns:
                self.screen.app.call_from_thread(self.screen.advance_to_step, ns)
        except Exception as e:
            self.screen.app.call_from_thread(
                self.screen.add_system_message, f"Docking failed: {e}", "error-text"
            )


# ---------------------------------------------------------------------------
# Step 9: Spatial Rank
# ---------------------------------------------------------------------------

class SpatialRankHandler(StepHandler):
    def enter(self) -> None:
        state = self.screen.app.current_state
        target = state.target_molecule

        if not target:
            self.screen.add_system_message("Target molecule missing.", "error-text")
            return

        # Use docked candidates if available
        if state.docking_results:
            docked_ids = {r.candidate_id for r in state.docking_results}
            candidates = [c for c in state.candidates if c.candidate_id in docked_ids]
        else:
            candidates = state.candidates

        if not candidates:
            self.screen.add_system_message("No candidates available.", "error-text")
            return

        self.screen.add_system_message(
            f"Running spatial ranking on {len(candidates)} candidates..."
        )
        self.screen.set_input_enabled(False)
        self.screen.run_worker(
            lambda: self._rank_worker(candidates, target),
            exclusive=True,
            thread=True,
        )

    def _rank_worker(self, candidates, target) -> None:
        try:
            results = self.screen.app.spatial_rank_adapter.rank_batch(candidates, target)
            state = self.screen.app.current_state
            state.spatial_ranks = results
            self.screen.app.save_state()

            sorted_results = sorted(results, key=lambda r: r.rank)
            lines = [f"Spatial ranking complete ({len(results)} candidates):"]
            for r in sorted_results[:15]:
                groups = ", ".join(r.detected_groups[:3])
                lines.append(
                    f"  #{r.rank} {r.candidate_id}: score={r.spatial_score:.4f} groups=[{groups}]"
                )
            if len(sorted_results) > 15:
                lines.append(f"  ... and {len(sorted_results) - 15} more")

            self.screen.app.call_from_thread(self.screen.add_system_message, "\n".join(lines))
            ns = _next_step(Step.SPATIAL_RANK)
            if ns:
                self.screen.app.call_from_thread(self.screen.advance_to_step, ns)
        except Exception as e:
            self.screen.app.call_from_thread(
                self.screen.add_system_message, f"Ranking failed: {e}", "error-text"
            )


# ---------------------------------------------------------------------------
# Step 10: Final Report
# ---------------------------------------------------------------------------

class ReportHandler(StepHandler):
    def enter(self) -> None:
        self.screen.set_input_enabled(False)
        self.screen.run_worker(self._build_report, exclusive=True, thread=True)

    def _build_report(self) -> None:
        state = self.screen.app.current_state

        # Build lookup maps
        spec_map = {r.candidate_id: r for r in state.specificity_results}
        dock_map = {r.candidate_id: r for r in state.docking_results}
        spatial_map = {r.candidate_id: r for r in state.spatial_ranks}

        ens_preds = [p for p in state.predictions if p.model_name == "ensemble"]
        sorted_preds = sorted(ens_preds, key=lambda x: x.probability or 0.0, reverse=True)

        # Filter removed
        kept_ids: set[str] | None = None
        if state.specificity_results:
            kept_ids = {
                r.candidate_id for r in state.specificity_results
                if r.status in ("kept", "skipped")
            }

        recommendations: list[FinalRecommendation] = []
        lines = ["=== FINAL REPORT ==="]
        for rank, p in enumerate(sorted_preds, start=1):
            cand_id = p.candidate_id
            if kept_ids is not None and cand_id not in kept_ids:
                continue

            cand = next((c for c in state.candidates if c.candidate_id == cand_id), None)

            spec = spec_map.get(cand_id)
            spec_status = spec.status if spec else "pending"

            dock = dock_map.get(cand_id)
            dock_score = f"{dock.docking_score:.3f}" if dock and dock.docking_score is not None else "-"

            spatial = spatial_map.get(cand_id)
            spatial_rank = str(spatial.rank) if spatial else "-"
            final_priority = spatial.rank if spatial and spatial.rank > 0 else rank

            seq_short = (cand.sequence[:30] + "...") if cand else ""

            rec = FinalRecommendation(
                candidate_id=cand_id,
                primary_score=p.probability or 0.0,
                specificity_status=spec_status,
                docking_score=dock.docking_score if dock else None,
                spatial_rank=spatial.rank if spatial else None,
                final_priority=final_priority,
            )
            recommendations.append(rec)
            lines.append(
                f"  #{final_priority} {cand_id} | "
                f"Score={p.probability:.4f} | Spec={spec_status} | "
                f"Dock={dock_score} | Spatial=#{spatial_rank}\n"
                f"         {seq_short}"
            )

        state.recommendations = recommendations
        self.screen.app.save_state()

        # LLM summary (best-effort, streamed)
        summary = ""
        try:
            skill = ReportSkill()
            rec_dicts = [r.model_dump() for r in recommendations[:10]]
            summary_result = _run_llm_interaction(
                self.screen,
                display_stream=lambda: skill.explain_summarize_stream(rec_dicts),
                structured_call=lambda: _validate_report_summary(skill.summarize(rec_dicts)),
            )
            summary = summary_result.get("summary", "")
            if summary:
                lines.append(f"\nSummary: {summary}")
        except Exception:
            lines.append("\n(Report generated from deterministic scoring results.)")

        lines.append("\nType 'export' to save, 'finish' to exit.")

        self.screen.app.call_from_thread(self.screen.add_system_message, "\n".join(lines))
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
        data = {
            "run_id": state.run_id,
            "recommendations": [r.model_dump() for r in state.recommendations],
            "specificity_results": [r.model_dump() for r in state.specificity_results],
            "docking_results": [r.model_dump() for r in state.docking_results],
            "spatial_ranks": [r.model_dump() for r in state.spatial_ranks],
        }
        path = self.screen.app.persistence.write_artifact(state.run_id, "final_report.json", data)
        self.screen.add_system_message(f"Report exported to {path}")
        self.screen.set_input_placeholder("Type 'finish' to exit")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_HANDLER_MAP: dict[Step, type[StepHandler]] = {
    Step.INTAKE: IntakeHandler,
    Step.SECONDARY_STRUCTURE: StructureHandler,
    Step.SITE_PROPOSAL: SiteProposalHandler,
    Step.CANDIDATE_ENUMERATION: EnumerationHandler,
    Step.PRIMARY_SCORING: ScoringHandler,
    Step.SPECIFICITY_FILTER: SpecificityHandler,
    Step.DOCKING_PREP: DockingSelectionHandler,  # backward-compat for persisted runs
    Step.DOCKING_SELECTION: DockingSelectionHandler,
    Step.DOCKING_RUN: DockingRunHandler,
    Step.SPATIAL_RANK: SpatialRankHandler,
    Step.FINAL_REPORT: ReportHandler,
}


def create_handler(step: Step, screen: Any) -> StepHandler:
    """Factory: create the appropriate handler for a step."""
    cls = _HANDLER_MAP.get(step)
    if cls is None:
        raise ValueError(f"No handler registered for step: {step}")
    return cls(screen)
