from __future__ import annotations

import heapq
import itertools
import json
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
from aptgent.workflow.context import (
    get_sequence,
    record_docking_recommendation_context,
    record_intake_context,
    record_site_proposal_context,
)
from aptgent.tui.widgets.chat_widgets import ProgressBubble
from aptgent.tui.widgets.structured_input import (
    ActionMenuPanel,
    DockingParamPanel,
    DockingStrategyPanel,
    MutationSitePanel,
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

    def run_worker(self, work: Callable[[], Any], *, activity: str) -> None:
        """Run a step worker with a visible activity status."""
        self.screen.show_activity(activity)
        self.screen.set_input_enabled(False)
        self.screen.run_worker(work, exclusive=True, thread=True)


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


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _coerce_float_list(values: Any, *, exact_len: int | None = None) -> list[float]:
    if not isinstance(values, list):
        return []
    result = [value for item in values if (value := _coerce_float(item)) is not None]
    if exact_len is not None and len(result) != exact_len:
        return []
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
            bubble = screen.add_streaming_message(markdown=True)

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

    screen.app.call_from_thread(screen.update_activity, "Processing structured result...")
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


def _format_intake_confirmation(
    *,
    sequence: str,
    target_text: str,
    resolved: TargetMolecule,
    modification_region: str | None,
    analogs: list[str],
    time_budget_hours: int | None,
) -> str:
    lines = [
        "Captured intake details.",
        f"Sequence: {sequence}",
    ]
    if resolved.resolution_status == "resolved":
        lines.append(f"Target: {resolved.resolved_name or target_text} ({resolved.smiles})")
    else:
        lines.append(f"Target: {target_text} (resolution failed)")
    if modification_region:
        lines.append(f"Requested modification region: {modification_region}")
    if analogs:
        lines.append(f"Specificity analogs: {', '.join(analogs)}")
    if time_budget_hours is not None:
        lines.append(f"Time budget: {time_budget_hours} hour(s)")
    return "\n".join(lines)


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


def _default_time_budget_hours(
    candidate_count: int,
    machine_profile: dict[str, Any],
    recommended_top_k: int,
    user_time_budget_hours: int | None,
) -> int:
    if user_time_budget_hours is not None:
        return max(user_time_budget_hours, 1)
    cpu_count = _coerce_int(machine_profile.get("cpu_count")) or 1
    target = max(recommended_top_k or candidate_count or 1, 1)
    estimated = (target + (cpu_count * 4) - 1) // (cpu_count * 4)
    return max(1, min(8, estimated or 1))


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
    recommended_time_budget = _coerce_int(result.get("recommended_time_budget_hours"))
    if recommended_time_budget is None or recommended_time_budget <= 0:
        recommended_time_budget = _default_time_budget_hours(
            candidate_count,
            machine_profile,
            top_k,
            time_budget_hours,
        )
    grid_size = _coerce_float_list(result.get("recommended_grid_size"), exact_len=3)
    if not grid_size:
        grid_size = [20.0, 20.0, 20.0]
    receptor_path_note = _clean_text(result.get("receptor_path_note")) or (
        "Provide the receptor PDBQT path from your prepared docking target."
    )
    grid_center_note = _clean_text(result.get("grid_center_note")) or (
        "Confirm the grid center manually from the binding region before running docking."
    )
    reason = _clean_text(result.get("reason")) or "Using a conservative docking batch size based on available resources."
    return {
        "recommended_time_budget_hours": recommended_time_budget,
        "recommended_top_k": top_k,
        "recommended_grid_size": grid_size,
        "receptor_path_note": receptor_path_note,
        "grid_center_note": grid_center_note,
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


def _format_docking_recommendation_markdown(
    *,
    candidate_count: int,
    machine_profile: dict[str, Any],
    time_budget_hours: int | None,
    recommended_top_k: int,
    recommended_grid_size: list[float],
    receptor_path_note: str,
    grid_center_note: str,
    reason: str,
) -> str:
    cpu_count = machine_profile.get("cpu_count", "?")
    memory_gb = machine_profile.get("memory_gb")
    memory_text = f"{memory_gb} GB" if memory_gb is not None else "unknown"
    budget_text = (
        f"{time_budget_hours} hour(s)"
        if time_budget_hours is not None
        else "not specified"
    )
    return (
        "### Recommended Docking Setup\n\n"
        f"- Candidates available: **{candidate_count}**\n"
        f"- Time budget: **{budget_text}**\n"
        f"- Suggested batch: **top {recommended_top_k}**\n"
        f"- Suggested grid box size: **{', '.join(f'{value:.1f}' for value in recommended_grid_size)}**\n"
        f"- Receptor path: {receptor_path_note}\n"
        f"- Grid center: {grid_center_note}\n"
        f"- Machine profile: **{cpu_count} CPU(s)**, **{memory_text}** memory\n\n"
        f"- Rationale: {reason}"
    )


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
        """Try to resolve user input directly as SMILES or molecule name."""
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
            confirmation = _format_intake_confirmation(
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
            ns = _next_step(Step.INTAKE)
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
            result = _run_llm_interaction(
                self.screen,
                display_stream=None,
                structured_call=lambda: _validate_intake_result(skill.extract(text)),
            )
        except Exception as e:
            self.screen.app.call_from_thread(
                self.screen.add_system_message, f"LLM error: {e}", "error-text"
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

        confirmation = _format_intake_confirmation(
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
        ns = _next_step(Step.INTAKE)
        if ns:
            self.screen.app.call_from_thread(self.screen.advance_to_step, ns)


# ---------------------------------------------------------------------------
# Step 2: Secondary Structure
# ---------------------------------------------------------------------------

class StructureHandler(StepHandler):
    def enter(self) -> None:
        state = self.screen.app.current_state
        seq = get_sequence(state) or ""
        if not seq:
            self.screen.add_system_message("Error: no sequence available.", "error-text")
            self.screen.set_input_enabled(True)
            return
        self.screen.add_system_message(f"Running RNAfold on: {seq}")
        self.run_worker(self._run_fold, activity="Folding secondary structure...")

    def _run_fold(self) -> None:
        state = self.screen.app.current_state
        seq = get_sequence(state) or ""
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
            self.screen.app.call_from_thread(self.screen.set_input_enabled, True)


# ---------------------------------------------------------------------------
# Step 3: Site Proposal
# ---------------------------------------------------------------------------

class SiteProposalHandler(StepHandler):
    def enter(self) -> None:
        state = self.screen.app.current_state
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

        self.run_worker(self._propose, activity="Analyzing mutation-tolerant sites...")

    def _propose(self) -> None:
        state = self.screen.app.current_state
        seq = get_sequence(state) or ""
        struct = state.secondary_structure

        try:
            skill = SiteProposalSkill()
            result = _validate_site_proposal_result(
                skill.propose(seq, struct),
                len(seq),
            )
        except Exception as e:
            self.screen.app.call_from_thread(
                self.screen.add_system_message, f"LLM error: {e}", "error-text"
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
        ns = _next_step(Step.SITE_PROPOSAL)
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


# ---------------------------------------------------------------------------
# Step 4: Candidate Enumeration
# ---------------------------------------------------------------------------

class EnumerationHandler(StepHandler):
    """Full enumeration + batch prediction + batch JSONL save + in-memory top-K heap."""

    _BASES = ["A", "T", "G", "C"]

    def enter(self) -> None:
        state = self.screen.app.current_state
        seq: str = get_sequence(state) or ""
        sites = state.confirmed_mutation_sites
        enum_cfg = self.screen.app.config.get("enumeration", {})
        batch_size = enum_cfg.get("batch_size", 1000)
        top_k_keep = enum_cfg.get("top_k_keep", 500)

        if not sites:
            self.screen.add_system_message(
                "No mutation sites selected. Please go back.", "error-text"
            )
            self.screen.set_input_enabled(True)
            return

        total_space = 4 ** len(sites)
        total_batches = (total_space + batch_size - 1) // batch_size

        self.screen.add_system_message(
            f"Mutation space: 4^{len(sites)} = {total_space:,} candidates\n"
            f"Batch size: {batch_size:,} | Batches: {total_batches:,} | "
            f"Top-K kept: {top_k_keep:,}\n"
            f"Each batch: enumerate → predict → save to JSONL"
        )
        self.run_worker(
            lambda: self._pipeline(
                seq, sites, total_space, batch_size, top_k_keep
            ),
            activity="Enumerating and scoring candidates...",
        )

    def _pipeline(
        self,
        seq: str,
        sites: list[int],
        total_space: int,
        batch_size: int,
        top_k_keep: int,
    ) -> None:
        from textual.worker import get_current_worker

        worker = get_current_worker()
        state = self.screen.app.current_state
        target = state.target_molecule
        can_score = bool(target and target.smiles)

        # Prepare JSONL artifact path
        run_dir = self.screen.app.persistence._run_dir(state.run_id)
        artifact_dir = run_dir / "artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        results_path = artifact_dir / "scored_candidates.jsonl"

        progress = self.screen.app.call_from_thread(
            self._create_progress_bubble,
            total_space,
        )

        top_heap: list[tuple[float, int, CandidateSequence, Any]] = []
        heap_counter = 0
        total_processed = 0
        total_binding = 0
        batch_num = 0
        total_batches = (total_space + batch_size - 1) // batch_size
        batch_buf: list[CandidateSequence] = []

        try:
            with open(results_path, "w", encoding="utf-8") as f:
                for combo in itertools.product(self._BASES, repeat=len(sites)):
                    if worker.is_cancelled:
                        return

                    cand = self._build_candidate(
                        seq, sites, combo, total_processed
                    )
                    batch_buf.append(cand)
                    total_processed += 1

                    if len(batch_buf) < batch_size and total_processed < total_space:
                        continue

                    # --- process one full batch ---
                    batch_num += 1
                    batch_preds: list[Any] = []

                    if can_score:
                        try:
                            batch_preds = (
                                self.screen.app.prediction_adapter.predict_batch(
                                    batch_buf, target
                                )
                            )
                        except Exception as exc:
                            self.screen.app.call_from_thread(
                                self.screen.add_system_message,
                                f"Batch {batch_num} scoring error: {exc}",
                                "warning-text",
                            )

                    for i, c in enumerate(batch_buf):
                        entry: dict[str, Any] = {"candidate": c.model_dump()}
                        if i < len(batch_preds):
                            pred = batch_preds[i]
                            entry["prediction"] = pred.model_dump()
                            prob = pred.probability or 0.0
                            if pred.label == 1:
                                total_binding += 1
                            heap_counter += 1
                            if len(top_heap) < top_k_keep:
                                heapq.heappush(
                                    top_heap,
                                    (prob, heap_counter, c, pred),
                                )
                            elif prob > top_heap[0][0]:
                                heapq.heapreplace(
                                    top_heap,
                                    (prob, heap_counter, c, pred),
                                )
                        f.write(
                            json.dumps(entry, ensure_ascii=False) + "\n"
                        )

                    f.flush()

                    info_parts = [
                        f"Batch {batch_num:,}/{total_batches:,}"
                    ]
                    if can_score:
                        info_parts.append(f"Binding: {total_binding:,}")
                        if top_heap:
                            best_prob = max(h[0] for h in top_heap)
                            info_parts.append(f"Best: {best_prob:.4f}")
                    self.screen.app.call_from_thread(
                        progress.set_progress,
                        total_processed,
                        " | ".join(info_parts),
                    )
                    batch_buf = []

        except Exception as exc:
            self.screen.app.call_from_thread(
                self.screen.add_system_message,
                f"Pipeline failed at candidate {total_processed:,}: {exc}",
                "error-text",
            )
            self.screen.app.call_from_thread(
                self.screen.set_input_enabled, True
            )
            return

        # --- extract top-K into state ---
        top_heap.sort(key=lambda x: x[0], reverse=True)
        top_candidates = [item[2] for item in top_heap]
        top_predictions = [item[3] for item in top_heap]

        state.candidates = top_candidates
        if top_predictions:
            state.predictions = top_predictions
        self.screen.app.save_state()

        finish_msg = f"Scored {total_processed:,} candidates"
        if can_score:
            finish_msg += (
                f", {total_binding:,} binding, "
                f"top {len(top_candidates)} kept"
            )
        finish_msg += f"\nResults: {results_path}"
        self.screen.app.call_from_thread(progress.finish, finish_msg)

        # Preview top candidates
        preview = []
        for c, p in zip(top_candidates[:10], top_predictions[:10]):
            label_str = "Bind" if p.label == 1 else "Non-bind"
            mut_str = ", ".join(
                f"{m.position}:{m.original}>{m.mutated}" for m in c.mutations
            )
            preview.append(
                f"  {c.candidate_id}: {label_str} P={p.probability:.4f} | {mut_str}"
            )
        if len(top_candidates) > 10:
            preview.append(f"  … and {len(top_candidates) - 10} more")
        if preview:
            self.screen.app.call_from_thread(
                self.screen.add_system_message, "\n".join(preview)
            )

        ns = _next_step(Step.CANDIDATE_ENUMERATION)
        if ns:
            self.screen.app.call_from_thread(self.screen.advance_to_step, ns)

    def _create_progress_bubble(self, total_space: int) -> ProgressBubble:
        progress = ProgressBubble(total_space, label="Enumerating & Scoring")
        self.screen.add_structured_widget(progress)
        return progress

    @staticmethod
    def _build_candidate(
        seq: str,
        sites: list[int],
        combo: tuple[str, ...],
        index: int,
    ) -> CandidateSequence:
        muts: list[Mutation] = []
        new_seq = list(seq)
        for idx, base in zip(sites, combo):
            muts.append(Mutation(position=idx, original=seq[idx], mutated=base))
            new_seq[idx] = base
        cand_seq = "".join(new_seq)
        edit_ratio = len(muts) / len(seq)
        return CandidateSequence(
            sequence=cand_seq,
            mutations=muts,
            edit_ratio=edit_ratio,
            candidate_id=f"cand_{index}",
        )


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
            self.screen.set_input_enabled(True)
            return

        # If predictions were already computed during the enumeration pipeline,
        # display a summary and advance immediately.
        if state.predictions:
            self._show_existing(state)
            return

        if not target or not target.smiles:
            self.screen.add_system_message(
                "Target molecule missing. Cannot score.", "error-text"
            )
            self.screen.set_input_enabled(True)
            return

        self.screen.add_system_message(
            f"Running ensemble prediction on {len(candidates)} candidates..."
        )
        self.run_worker(self._score, activity="Running ensemble prediction...")

    def _show_existing(self, state: Any) -> None:
        ens_preds = [p for p in state.predictions if p.model_name == "ensemble"]
        sorted_preds = sorted(
            ens_preds, key=lambda x: x.probability or 0.0, reverse=True
        )
        lines = [
            f"Scoring already completed during enumeration "
            f"({len(sorted_preds)} candidates):"
        ]
        for p in sorted_preds[:10]:
            label_str = "Binding" if p.label == 1 else "Non-binding"
            lines.append(
                f"  {p.candidate_id}: {label_str} (P={p.probability:.4f})"
            )
        if len(sorted_preds) > 10:
            lines.append(f"  ... and {len(sorted_preds) - 10} more")
        self.screen.add_system_message("\n".join(lines))
        ns = _next_step(Step.PRIMARY_SCORING)
        if ns:
            self.screen.advance_to_step(ns)

    def _score(self) -> None:
        state = self.screen.app.current_state
        candidates = state.candidates
        target = state.target_molecule

        try:
            results = self.screen.app.prediction_adapter.predict_batch(candidates, target)
            state.predictions = results
            self.screen.app.save_state()

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
            self.screen.app.call_from_thread(self.screen.set_input_enabled, True)


# ---------------------------------------------------------------------------
# Step 6: Specificity Filter
# ---------------------------------------------------------------------------

class SpecificityHandler(StepHandler):
    def enter(self) -> None:
        self.screen.add_system_message(
            "Step 6: Specificity Filter\n"
            "You can provide analog molecules, ask the LLM to suggest them, or skip this step."
        )
        self.screen.add_structured_widget(self._build_choice_panel())
        self.screen.set_input_enabled(True)
        self.screen.set_input_placeholder("Type 'skip', 'suggest', or analog names (comma-separated).")

    def handle_user_input(self, text: str) -> None:
        text_lower = text.strip().lower()
        if text_lower == "skip":
            self._skip()
        elif text_lower == "suggest":
            self._show_specificity_panel()
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
        if action in {"suggest", "suggest-analogs"}:
            self._show_specificity_panel()
            self._suggest()
        elif action == "custom-analogs":
            self._show_specificity_panel()
            self.screen.set_input_enabled(True)
        elif action == "skip-specificity":
            self._skip()

    def _suggest(self) -> None:
        self.run_worker(self._suggest_worker, activity="Suggesting analog molecules...")

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
        self.run_worker(
            lambda: self._filter_worker(candidates, target, analogs),
            activity="Running specificity cross-prediction...",
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

    def _build_choice_panel(self) -> ActionMenuPanel:
        return ActionMenuPanel(
            Step.SPECIFICITY_FILTER,
            "Choose how to provide analog molecules",
            [
                (
                    "suggest-analogs",
                    "Use Recommended Analogs",
                    "Ask the LLM for likely confounding analog molecules, then review them.",
                ),
                (
                    "custom-analogs",
                    "Enter My Own Analogs",
                    "Open a focused input panel and provide comma-separated names or SMILES.",
                ),
                (
                    "skip-specificity",
                    "Skip This Step",
                    "Continue without specificity filtering.",
                ),
            ],
        )

    def _show_specificity_panel(self, analogs_text: str = "") -> None:
        target = self.screen.app.current_state.target_molecule
        panel = SpecificityPanel(
            target_name=target.input_text if target else "",
            analogs_text=analogs_text,
        )
        self.screen.add_structured_widget(panel)


# ---------------------------------------------------------------------------
# Step 7: Docking Selection
# ---------------------------------------------------------------------------

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
        text_lower = text.strip().lower()
        if "skip" in text_lower:
            # Skip to spatial rank
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
        )
        state.time_budget = data.get("time_budget")
        recommendation.accepted = bool(data.get("accepted_recommendation"))
        recommendation.phase = "editing_form"
        self.screen.app.save_state()
        self.screen.add_system_message(
            f"Docking plan: top-{top_k} candidates, "
            f"receptor={data.get('receptor_path', 'N/A')}"
        )
        ns = _next_step(Step.DOCKING_SELECTION)
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
            return

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
            recommended_time_budget = result.get("recommended_time_budget_hours")
            top_k = result.get("recommended_top_k", 0)
            grid_size = result.get("recommended_grid_size", [])
            receptor_path_note = result.get("receptor_path_note", "")
            grid_center_note = result.get("grid_center_note", "")
            reason = result.get("reason", "")
            markdown = _format_docking_recommendation_markdown(
                candidate_count=len(state.candidates),
                machine_profile=profile,
                time_budget_hours=recommended_time_budget,
                recommended_top_k=top_k,
                recommended_grid_size=grid_size,
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
        except Exception as e:
            self.screen.app.call_from_thread(
                self.screen.add_system_message, f"Recommendation failed: {e}", "error-text"
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
        state.docking_plan = DockingPlan(recommended_top_k=0)
        recommendation = state.context.docking_recommendation
        recommendation.display_markdown = ""
        recommendation.phase = "initial"
        recommendation.strategy = ""
        recommendation.accepted = False
        self.screen.app.save_state()
        self.screen.add_system_message("Docking skipped.")
        ns = _next_step(Step.DOCKING_SELECTION)
        if ns:
            self.screen.advance_to_step(ns)


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
            self.screen.set_input_enabled(True)
            return

        if not plan.receptor_path or not Path(plan.receptor_path).exists():
            self.screen.add_system_message(
                f"Receptor file not found: {plan.receptor_path}",
                "error-text",
            )
            self.screen.set_input_enabled(True)
            return

        if not plan.grid_center or not plan.grid_size:
            self.screen.add_system_message("Grid box parameters not set.", "error-text")
            self.screen.set_input_enabled(True)
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
        self.run_worker(
            lambda: self._dock_worker(top_candidates, target),
            activity="Running docking jobs...",
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
            self.screen.app.call_from_thread(self.screen.set_input_enabled, True)


# ---------------------------------------------------------------------------
# Step 9: Spatial Rank
# ---------------------------------------------------------------------------

class SpatialRankHandler(StepHandler):
    def enter(self) -> None:
        state = self.screen.app.current_state
        target = state.target_molecule

        if not target:
            self.screen.add_system_message("Target molecule missing.", "error-text")
            self.screen.set_input_enabled(True)
            return

        # Use docked candidates if available
        if state.docking_results:
            docked_ids = {r.candidate_id for r in state.docking_results}
            candidates = [c for c in state.candidates if c.candidate_id in docked_ids]
        else:
            candidates = state.candidates

        if not candidates:
            self.screen.add_system_message("No candidates available.", "error-text")
            self.screen.set_input_enabled(True)
            return

        self.screen.add_system_message(
            f"Running spatial ranking on {len(candidates)} candidates..."
        )
        self.run_worker(
            lambda: self._rank_worker(candidates, target),
            activity="Ranking spatial interactions...",
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
            self.screen.app.call_from_thread(self.screen.set_input_enabled, True)


# ---------------------------------------------------------------------------
# Step 10: Final Report
# ---------------------------------------------------------------------------

class ReportHandler(StepHandler):
    def enter(self) -> None:
        self.run_worker(self._build_report, activity="Compiling final report...")

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
