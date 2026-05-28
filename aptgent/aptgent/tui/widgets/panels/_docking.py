from __future__ import annotations

import logging

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.css.query import NoMatches
from textual.widgets import Button, Input, Static

from aptgent.domain.enums import Step

from ._core import StructuredActionRequested, StructuredInputSubmitted, _BaseStructuredPanel

_log = logging.getLogger(__name__)


class DockingStrategyPanel(_BaseStructuredPanel):
    """Phase 1: full docking parameter form (Vina knobs + skip).

    This panel is the **single editable source** for every docking parameter
    the user can change. The downstream :class:`DockingParamPanel` is a
    read-only confirmation view; advanced edits should happen here.

    LLM Hint and the chat free-text input both call back via
    :meth:`apply_overrides` to populate the form. The user still has to
    press Continue to submit.
    """

    DEFAULT_CSS = """
    DockingStrategyPanel > .panel-help {
        margin: 1 0;
    }
    DockingStrategyPanel > .panel-note {
        color: $text-muted;
        margin: 0 0 1 0;
    }
    DockingStrategyPanel > .section-heading {
        text-style: bold;
        margin-top: 1;
    }
    DockingStrategyPanel > Input {
        margin: 0 0 1 0;
    }
    DockingStrategyPanel Horizontal {
        height: auto;
    }
    DockingStrategyPanel Horizontal > Button {
        margin-right: 1;
    }
    """

    _FIELD_IDS = {
        "top_k": "dock-plan-top-k",
        "exhaustiveness": "dock-plan-exhaustiveness",
        "num_modes": "dock-plan-num-modes",
        "energy_range": "dock-plan-energy-range",
        "grid_padding_angstrom": "dock-plan-padding",
        "per_ligand_timeout_seconds": "dock-plan-per-ligand-timeout",
        "time_budget_hours": "dock-plan-time-budget",
        "seed": "dock-plan-seed",
    }

    def __init__(
        self,
        *,
        machine_profile: dict | None = None,
        candidate_count: int = 0,
        default_top_k: int = 5,
        default_exhaustiveness: int = 8,
        default_num_modes: int = 9,
        default_energy_range: float = 3.0,
        default_grid_padding_angstrom: float = 4.0,
        default_per_ligand_timeout_seconds: int | None = None,
        default_time_budget_hours: int | None = None,
        default_seed: int | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.machine_profile = machine_profile or {}
        self.candidate_count = candidate_count
        ceiling = candidate_count if candidate_count else default_top_k
        self.default_top_k = max(1, min(default_top_k, ceiling))
        self.default_exhaustiveness = default_exhaustiveness
        self.default_num_modes = default_num_modes
        self.default_energy_range = default_energy_range
        self.default_grid_padding_angstrom = default_grid_padding_angstrom
        self.default_per_ligand_timeout_seconds = default_per_ligand_timeout_seconds
        self.default_time_budget_hours = default_time_budget_hours
        self.default_seed = default_seed

    def compose(self) -> ComposeResult:
        yield Static("Docking Selection \u2014 Step 7", classes="panel-title")
        yield Static(
            "All Vina parameters live here. Use natural language in the chat "
            "input below to fill these fields (e.g. \"top 8, exhaustiveness 32, "
            "seed 42\"). Click Continue when ready.",
            classes="panel-help",
        )
        yield Static(f"[dim]{self._machine_info()}[/]")
        yield Static(f"Available candidates: [bold]{self.candidate_count}[/bold]")

        yield Static("Core", classes="section-heading")
        yield Static("Top-K candidates to dock (default: 5):")
        top_k_input = Input(id=self._FIELD_IDS["top_k"], placeholder="5")
        top_k_input.value = str(self.default_top_k)
        yield top_k_input

        yield Static("Exhaustiveness (Vina default 8; 16/32 for generous compute):")
        exh_input = Input(id=self._FIELD_IDS["exhaustiveness"], placeholder="8")
        exh_input.value = str(self.default_exhaustiveness)
        yield exh_input

        yield Static("Vina options", classes="section-heading")
        yield Static("num_modes (Vina default 9, range 1..20):")
        nm_input = Input(id=self._FIELD_IDS["num_modes"], placeholder="9")
        nm_input.value = str(self.default_num_modes)
        yield nm_input

        yield Static("energy_range kcal/mol (Vina default 3.0):")
        er_input = Input(id=self._FIELD_IDS["energy_range"], placeholder="3.0")
        er_input.value = str(self.default_energy_range)
        yield er_input

        yield Static("Grid padding \u00c5 (default 4.0; box auto-covers aptamer):")
        pad_input = Input(
            id=self._FIELD_IDS["grid_padding_angstrom"],
            placeholder="4.0",
        )
        pad_input.value = str(self.default_grid_padding_angstrom)
        yield pad_input

        yield Static("Per-ligand timeout sec (blank = use config default):")
        timeout_input = Input(
            id=self._FIELD_IDS["per_ligand_timeout_seconds"],
            placeholder="1800",
        )
        if self.default_per_ligand_timeout_seconds is not None:
            timeout_input.value = str(self.default_per_ligand_timeout_seconds)
        yield timeout_input

        yield Static("Advanced", classes="section-heading")
        yield Static(
            "Time budget hours (blank = unset, advisory only):",
        )
        budget_input = Input(
            id=self._FIELD_IDS["time_budget_hours"],
            placeholder="e.g. 4",
        )
        if self.default_time_budget_hours is not None:
            budget_input.value = str(self.default_time_budget_hours)
        yield budget_input

        yield Static("Seed (blank = let Vina randomize):")
        seed_input = Input(id=self._FIELD_IDS["seed"], placeholder="optional")
        if self.default_seed is not None:
            seed_input.value = str(self.default_seed)
        yield seed_input

        with Horizontal():
            yield Button("Continue", id="btn-dock-plan-continue", variant="primary")
            yield Button("Get LLM Hint", id="btn-dock-plan-llm")
            yield Button("Skip Docking", id="btn-dock-plan-skip", variant="warning")

    def apply_overrides(self, overrides: dict) -> list[str]:
        """Write *overrides* (already-validated dict) back into the Inputs.

        Returns the list of field IDs (form-style names) that were updated.
        Unknown keys are silently ignored. The method is safe to call from
        the Textual UI thread (caller handles scheduling).
        """
        applied: list[str] = []
        for key, widget_id in self._FIELD_IDS.items():
            if key not in overrides:
                continue
            value = overrides[key]
            if value is None:
                continue
            try:
                input_widget = self.query_one(f"#{widget_id}", Input)
            except NoMatches:
                _log.debug(
                    "DockingStrategyPanel: missing input %s during apply_overrides",
                    widget_id,
                    exc_info=True,
                )
                continue
            if isinstance(value, float) and value.is_integer():
                input_widget.value = str(int(value))
            else:
                input_widget.value = str(value)
            applied.append(key)
        return applied

    def _machine_info(self) -> str:
        if self.machine_profile:
            cpu_count = self.machine_profile.get("cpu_count", "?")
            memory_gb = self.machine_profile.get("memory_gb")
            if memory_gb is not None:
                return f"CPUs: {cpu_count}  |  Memory: {memory_gb} GB"
            return f"CPUs: {cpu_count}"
        return "Machine profile unavailable"

    def on_mount(self) -> None:
        try:
            self.query_one(f"#{self._FIELD_IDS['top_k']}", Input).focus()
        except NoMatches:
            _log.debug("Focus target missing during on_mount", exc_info=True)

    def _read(self, field: str) -> str:
        try:
            return self.query_one(f"#{self._FIELD_IDS[field]}", Input).value.strip()
        except NoMatches:
            return ""

    def live_params(self) -> dict:
        """Return the current live values from each Input widget.

        Must be called from the UI thread. Used by the NL-parse worker to
        snapshot the form state before the worker lambda executes off-thread.
        """
        def _int(val: str) -> int | None:
            try:
                return int(val) if val else None
            except ValueError:
                return None

        def _float(val: str) -> float | None:
            try:
                return float(val) if val else None
            except ValueError:
                return None

        return {
            "top_k": _int(self._read("top_k")),
            "exhaustiveness": _int(self._read("exhaustiveness")),
            "num_modes": _int(self._read("num_modes")),
            "energy_range": _float(self._read("energy_range")),
            "grid_padding_angstrom": _float(self._read("grid_padding_angstrom")),
            "per_ligand_timeout_seconds": _int(
                self._read("per_ligand_timeout_seconds")
            ),
            "time_budget_hours": _int(self._read("time_budget_hours")),
            "seed": _int(self._read("seed")),
        }

    def _collect_payload(self) -> dict:
        def _opt(field: str) -> str | None:
            v = self._read(field)
            return v if v else None

        return {
            "phase": "strategy_submitted",
            "top_k": self._read("top_k") or str(self.default_top_k),
            "exhaustiveness": self._read("exhaustiveness")
            or str(self.default_exhaustiveness),
            "num_modes": self._read("num_modes") or str(self.default_num_modes),
            "energy_range": self._read("energy_range")
            or str(self.default_energy_range),
            "grid_padding_angstrom": self._read("grid_padding_angstrom")
            or str(self.default_grid_padding_angstrom),
            "per_ligand_timeout_seconds": _opt("per_ligand_timeout_seconds"),
            "time_budget_hours": _opt("time_budget_hours"),
            "seed": _opt("seed"),
        }

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-dock-plan-continue":
            self.post_message(
                StructuredInputSubmitted(
                    Step.DOCKING_SELECTION,
                    self._collect_payload(),
                )
            )
        elif event.button.id == "btn-dock-plan-llm":
            self.post_message(
                StructuredActionRequested(
                    Step.DOCKING_SELECTION,
                    "llm-hint",
                )
            )
        elif event.button.id == "btn-dock-plan-skip":
            self.post_message(
                StructuredActionRequested(
                    Step.DOCKING_SELECTION,
                    "strategy:skip",
                )
            )


class DockingSourcePanel(_BaseStructuredPanel):
    """Phase 2: choose receptor source (manual upload vs RNAComposer auto)."""

    DEFAULT_CSS = """
    DockingSourcePanel > .panel-help {
        margin: 1 0;
    }
    DockingSourcePanel Horizontal {
        height: auto;
    }
    DockingSourcePanel Horizontal > Button {
        margin-right: 1;
    }
    """

    def __init__(self, *, top_k: int = 5, **kwargs) -> None:
        super().__init__(**kwargs)
        self.top_k = top_k

    def compose(self) -> ComposeResult:
        yield Static("How will the receptor PDBQTs be prepared?", classes="panel-title")
        yield Static(
            "Each of the top candidates needs its own 3D structure. "
            "Each candidate is predicted via RNAComposer and hydrogens "
            "are added in AutoDockTools.",
            classes="panel-help",
        )
        yield Static(f"Top candidates to prepare: [bold]{self.top_k}[/bold]")
        with Horizontal():
            yield Button(
                "Manual upload",
                id="btn-source-manual",
                variant="primary",
            )
            yield Button(
                "RNAComposer (auto)",
                id="btn-source-rnacomposer",
                variant="warning",
            )

    def on_mount(self) -> None:
        try:
            self.query_one("#btn-source-manual", Button).focus()
        except NoMatches:
            _log.debug("Focus target missing during on_mount", exc_info=True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-source-manual":
            self.post_message(
                StructuredActionRequested(Step.DOCKING_SELECTION, "source:manual")
            )
        elif event.button.id == "btn-source-rnacomposer":
            self.post_message(
                StructuredActionRequested(Step.DOCKING_SELECTION, "source:rnacomposer")
            )


class DockingManualUploadPanel(_BaseStructuredPanel):
    """Phase 3 (manual): user supplies a directory with `cand_<id>.pdb/.pdbqt`."""

    DEFAULT_CSS = """
    DockingManualUploadPanel > .panel-help {
        margin: 1 0;
    }
    DockingManualUploadPanel > .panel-note {
        color: $text-muted;
        margin-bottom: 1;
    }
    DockingManualUploadPanel > Input {
        margin: 1 0;
    }
    DockingManualUploadPanel Horizontal {
        height: auto;
    }
    DockingManualUploadPanel Horizontal > Button {
        margin-right: 1;
    }
    """

    def __init__(
        self,
        *,
        export_dir: str,
        candidate_ids: list[str],
        default_structures_dir: str = "",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.export_dir = export_dir
        self.candidate_ids = candidate_ids
        self.default_structures_dir = default_structures_dir

    def compose(self) -> ComposeResult:
        yield Static("Manual receptor upload", classes="panel-title")
        yield Static(
            "The selected candidate sequences have been written to disk. "
            "Predict each one's 3D structure (e.g. RNAComposer + ADT), then "
            "drop the resulting files into a single directory named after each "
            f"candidate id ({len(self.candidate_ids)} files total) using the "
            "convention [bold]<candidate_id>.pdb[/bold] or "
            "[bold]<candidate_id>.pdbqt[/bold].",
            classes="panel-help",
        )
        if self.candidate_ids:
            preview = ", ".join(f"{cid}.pdb" for cid in self.candidate_ids[:5])
            extra = "" if len(self.candidate_ids) <= 5 else f", \u2026 ({len(self.candidate_ids)} total)"
            yield Static(
                f"[dim]Expected files: {preview}{extra}[/]",
                classes="panel-note",
            )
        yield Static(f"Sequences exported to: [bold]{self.export_dir}[/bold]")
        yield Static("Path to your prepared structures directory:")
        dir_input = Input(
            id="dock-structures-dir",
            placeholder="/path/to/structures",
        )
        dir_input.value = self.default_structures_dir
        yield dir_input
        with Horizontal():
            yield Button("Load structures", id="btn-load-structures", variant="primary")
            yield Button("Back", id="btn-manual-back")

    def on_mount(self) -> None:
        try:
            self.query_one("#dock-structures-dir", Input).focus()
        except NoMatches:
            _log.debug("Focus target missing during on_mount", exc_info=True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-load-structures":
            path = self.query_one("#dock-structures-dir", Input).value.strip()
            self.post_message(
                StructuredInputSubmitted(
                    Step.DOCKING_SELECTION,
                    {"phase": "manual_upload", "structures_dir": path},
                )
            )
        elif event.button.id == "btn-manual-back":
            self.post_message(
                StructuredActionRequested(Step.DOCKING_SELECTION, "source:back")
            )


class DockingRNAComposerProgressPanel(_BaseStructuredPanel):
    """Phase 3 (auto): show RNAComposer scraping progress + cancel button."""

    DEFAULT_CSS = """
    DockingRNAComposerProgressPanel > .panel-help {
        margin: 1 0;
    }
    DockingRNAComposerProgressPanel > .panel-note {
        color: $text-muted;
        margin-bottom: 1;
    }
    DockingRNAComposerProgressPanel Horizontal {
        height: auto;
    }
    """

    def __init__(
        self,
        *,
        total: int = 0,
        completed: int = 0,
        current_candidate: str = "",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.total = total
        self.completed = completed
        self.current_candidate = current_candidate

    def compose(self) -> ComposeResult:
        yield Static(
            "RNAComposer structure preparation",
            classes="panel-title",
        )
        yield Static(
            "Submitting each candidate sequence to RNAComposer, converting "
            "RNA \u2192 DNA, adding hydrogens, and computing the search box. "
            "This may take a few minutes per candidate.",
            classes="panel-help",
        )
        progress = f"{self.completed} / {self.total} done"
        if self.current_candidate:
            progress += f" \u2014 current: {self.current_candidate}"
        yield Static(progress, classes="panel-note", id="dock-rnacomposer-progress")
        with Horizontal():
            yield Button("Cancel", id="btn-rnacomposer-cancel", variant="warning")

    def update_progress(
        self,
        *,
        completed: int,
        total: int,
        current_candidate: str = "",
    ) -> None:
        self.completed = completed
        self.total = total
        self.current_candidate = current_candidate
        try:
            progress = f"{completed} / {total} done"
            if current_candidate:
                progress += f" \u2014 current: {current_candidate}"
            self.query_one("#dock-rnacomposer-progress", Static).update(progress)
        except NoMatches:
            _log.debug("Progress label missing during update", exc_info=True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-rnacomposer-cancel":
            self.post_message(
                StructuredActionRequested(Step.DOCKING_SELECTION, "rnacomposer:cancel")
            )


class DockingParamPanel(_BaseStructuredPanel):
    """Final docking confirmation (read-only).

    By the time this panel is shown, every Vina knob was already set in
    Phase 1 (:class:`DockingStrategyPanel`) and the per-candidate
    receptors + search boxes are prepared. This view just summarises the
    plan and offers:

    - **Cover whole aptamer (recompute boxes)** \u2014 re-derive every box from
      the receptor geometry using ``grid_padding_angstrom`` from the plan.
    - **Submit & Continue** \u2014 advance to the docking run.

    No numeric edits happen here; jump back to Phase 1 to change params.
    """

    DEFAULT_CSS = """
    DockingParamPanel > .panel-help {
        margin: 1 0;
    }
    DockingParamPanel > .panel-note {
        color: $text-muted;
        margin-bottom: 1;
    }
    DockingParamPanel > .param-summary {
        margin: 1 0;
    }
    DockingParamPanel Horizontal {
        height: auto;
    }
    DockingParamPanel Horizontal > Button {
        margin-right: 1;
    }
    DockingParamPanel > .receptor-summary {
        margin: 1 0;
        max-height: 12;
        overflow: auto;
    }
    """

    def __init__(
        self,
        *,
        mode: str = "manual",
        machine_profile: dict | None = None,
        time_budget: int | None = None,
        recommended_exhaustiveness: int | None = None,
        recommendation_reason: str = "",
        accepted_recommendation: bool = False,
        receptor_paths: dict[str, str] | None = None,
        grid_boxes: dict[str, dict[str, list[float]]] | None = None,
        grid_padding_angstrom: float = 4.0,
        num_modes: int = 9,
        energy_range: float = 3.0,
        per_ligand_timeout_seconds: int | None = None,
        seed: int | None = None,
        top_k: int | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.mode = mode
        self.machine_profile = machine_profile or {}
        self.time_budget = time_budget
        self.recommended_exhaustiveness = recommended_exhaustiveness or 8
        self.recommendation_reason = recommendation_reason
        self.accepted_recommendation = accepted_recommendation
        self.receptor_paths = dict(receptor_paths or {})
        self.grid_boxes = dict(grid_boxes or {})
        self.grid_padding_angstrom = grid_padding_angstrom
        self.num_modes = num_modes
        self.energy_range = energy_range
        self.per_ligand_timeout_seconds = per_ligand_timeout_seconds
        self.seed = seed
        self.top_k = top_k or len(self.receptor_paths)

    def compose(self) -> ComposeResult:
        yield Static("Docking Configuration \u2014 Confirmation", classes="panel-title")
        yield Static(
            "All parameters were already set in Step 7 / Phase 1. Review the "
            "summary below and submit, or press \"Cover whole aptamer\" to "
            "recompute every search box from the receptor geometry. To change "
            "any number, jump back to Phase 1.",
            classes="panel-help",
        )
        if self.recommendation_reason:
            yield Static(self.recommendation_reason, classes="panel-note")
        yield Static(f"[dim]{self._machine_info()}[/]")

        yield Static(self._param_summary(), classes="param-summary")

        yield Static(f"Per-receptor structures ({len(self.receptor_paths)} loaded)")
        yield Static(self._receptor_summary(), classes="receptor-summary")

        with Horizontal():
            yield Button(
                "Cover whole aptamer (recompute boxes)",
                id="btn-cover-aptamer",
                variant="warning",
            )
            yield Button(
                "Submit & Continue",
                id="btn-submit-dock",
                variant="success",
            )

    def _param_summary(self) -> str:
        timeout_text = (
            f"{self.per_ligand_timeout_seconds} s"
            if self.per_ligand_timeout_seconds is not None
            else "config default"
        )
        seed_text = (
            str(self.seed) if self.seed is not None else "unset (Vina random)"
        )
        budget_text = (
            f"{self.time_budget} h" if self.time_budget is not None else "not set"
        )
        return (
            f"\u2022 top_k: [bold]{self.top_k}[/]\n"
            f"\u2022 exhaustiveness: [bold]{self.recommended_exhaustiveness}[/]\n"
            f"\u2022 num_modes: [bold]{self.num_modes}[/]\n"
            f"\u2022 energy_range: [bold]{self.energy_range}[/] kcal/mol\n"
            f"\u2022 grid padding: [bold]{self.grid_padding_angstrom}[/] \u00c5\n"
            f"\u2022 per-ligand timeout: [bold]{timeout_text}[/]\n"
            f"\u2022 time budget (advisory): [bold]{budget_text}[/]\n"
            f"\u2022 seed: [bold]{seed_text}[/]"
        )

    def _receptor_summary(self) -> str:
        if not self.receptor_paths:
            return "[red]No per-candidate receptors loaded yet.[/]"
        rows: list[str] = []
        for cand_id, path in list(self.receptor_paths.items())[:8]:
            box = self.grid_boxes.get(cand_id)
            if box:
                center = box.get("center", [])
                size = box.get("size", [])
                if len(center) == 3 and len(size) == 3:
                    rows.append(
                        f"\u2022 {cand_id}: center=({center[0]:.1f}, "
                        f"{center[1]:.1f}, {center[2]:.1f}) "
                        f"size=({size[0]:.1f}, {size[1]:.1f}, {size[2]:.1f})"
                    )
                    continue
            rows.append(f"\u2022 {cand_id}: [dim]{path}[/]")
        if len(self.receptor_paths) > 8:
            rows.append(f"\u2026 and {len(self.receptor_paths) - 8} more")
        return "\n".join(rows)

    def _machine_info(self) -> str:
        import os

        if self.machine_profile:
            cpu_count = self.machine_profile.get("cpu_count", "?")
            memory_gb = self.machine_profile.get("memory_gb")
            if memory_gb is not None:
                return f"CPUs: {cpu_count}  |  Memory: {memory_gb} GB"
            return f"CPUs: {cpu_count}"

        try:
            import psutil

            mem = round(psutil.virtual_memory().total / (1024 ** 3), 2)
            return f"CPUs: {os.cpu_count() or '?'}  |  Memory: {mem} GB"
        except Exception:
            return f"CPUs: {os.cpu_count() or '?'}"

    def on_mount(self) -> None:
        try:
            self.query_one("#btn-submit-dock", Button).focus()
        except NoMatches:
            _log.debug("Focus target missing during on_mount", exc_info=True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-submit-dock":
            self.post_message(
                StructuredInputSubmitted(Step.DOCKING_SELECTION, self._plan_payload())
            )
        elif event.button.id == "btn-cover-aptamer":
            self.post_message(
                StructuredActionRequested(
                    Step.DOCKING_SELECTION,
                    f"cover-aptamer:{self.grid_padding_angstrom}",
                )
            )

    def _plan_payload(self) -> dict:
        return {
            "phase": "param_submitted",
            "time_budget": self.time_budget,
            "exhaustiveness": self.recommended_exhaustiveness,
            "grid_padding_angstrom": self.grid_padding_angstrom,
            "num_modes": self.num_modes,
            "energy_range": self.energy_range,
            "per_ligand_timeout_seconds": self.per_ligand_timeout_seconds,
            "seed": self.seed,
            "recommendation_reason": self.recommendation_reason,
            "uses_recommendation": self.mode == "llm",
            "accepted_recommendation": self.accepted_recommendation,
        }
