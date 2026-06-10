from __future__ import annotations

import logging
import os

from textual.app import ComposeResult
from textual.containers import Horizontal, HorizontalGroup, VerticalGroup
from textual.css.query import NoMatches
from textual.widgets import Button, Input, Static

from aptgent.domain.enums import Step
from aptgent.tui.widgets.chat_widgets import _render_progress_bar

from ._core import StructuredActionRequested, StructuredInputSubmitted, _BaseStructuredPanel

_log = logging.getLogger(__name__)


def _machine_info(machine_profile: dict | None) -> str:
    if machine_profile:
        cpu_count = machine_profile.get("cpu_count", "?")
        memory_gb = machine_profile.get("memory_gb")
        if memory_gb is not None:
            return f"CPUs: {cpu_count}  |  Memory: {memory_gb} GB"
        return f"CPUs: {cpu_count}"

    try:
        import psutil

        mem = round(psutil.virtual_memory().total / (1024 ** 3), 2)
        return f"CPUs: {os.cpu_count() or '?'}  |  Memory: {mem} GB"
    except Exception:
        return f"CPUs: {os.cpu_count() or '?'}"


class DockingStrategyPanel(_BaseStructuredPanel):
    """Phase 1: full docking parameter form (Vina knobs).

    This panel is the **single editable source** for every docking parameter
    the user can change. The downstream :class:`DockingParamPanel` is a
    read-only confirmation view; advanced edits should happen here.

    LLM Hint and the chat free-text input both call back via
    :meth:`apply_overrides` to populate the form. The user still has to
    press Continue to submit.

    When *confirm_only* is True the panel shows pre-filled values with only
    a Continue button — used after an LLM recommendation so the user just
    confirms.
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
    DockingStrategyPanel .field-col {
        width: 1fr;
        height: auto;
        padding-right: 2;
    }
    DockingStrategyPanel .field-label {
        height: 1;
    }
    DockingStrategyPanel .field-col Input {
        margin: 0 0 1 0;
    }
    """

    _FIELD_IDS = {
        "top_k": "dock-plan-top-k",
        "affinity_top_k": "dock-plan-affinity-top-k",
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
        default_top_k: int = 100,
        default_affinity_top_k: int | None = None,
        default_exhaustiveness: int = 8,
        default_num_modes: int = 9,
        default_energy_range: float = 3.0,
        default_grid_padding_angstrom: float = 4.0,
        default_per_ligand_timeout_seconds: int | None = None,
        default_time_budget_hours: int | None = None,
        default_seed: int | None = None,
        confirm_only: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.machine_profile = machine_profile or {}
        self.candidate_count = candidate_count
        self.confirm_only = confirm_only
        ceiling = candidate_count if candidate_count else default_top_k
        self.default_top_k = max(1, min(default_top_k, ceiling))
        self.default_affinity_top_k = (
            default_affinity_top_k if default_affinity_top_k is not None
            else min(5, self.default_top_k)
        )
        self.default_exhaustiveness = default_exhaustiveness
        self.default_num_modes = default_num_modes
        self.default_energy_range = default_energy_range
        self.default_grid_padding_angstrom = default_grid_padding_angstrom
        self.default_per_ligand_timeout_seconds = default_per_ligand_timeout_seconds
        self.default_time_budget_hours = default_time_budget_hours
        self.default_seed = default_seed

    def compose(self) -> ComposeResult:
        if self.confirm_only:
            yield Static("Docking Recommendation \u2014 Confirm", classes="panel-title")
            yield Static(
                "Values below have been pre-filled based on the recommendation. "
                "Review and press Continue to proceed.",
                classes="panel-help",
            )
        else:
            yield Static("Docking Selection \u2014 Step 6", classes="panel-title")
            yield Static(
                "Configure docking parameters below, or use the chat input to "
                "describe what you want (e.g. \"dock 8, exhaustiveness 32\"). "
                "Click Continue when ready.",
                classes="panel-help",
            )
        yield Static(f"[dim]{self._machine_info()}[/]")
        yield Static(f"Available candidates: [bold]{self.candidate_count}[/bold]")

        # --- Core: candidate selection ---
        yield Static("Candidate Selection", classes="section-heading")
        with HorizontalGroup():
            with VerticalGroup(classes="field-col"):
                yield Static("Candidates to dock:", classes="field-label")
                top_k_input = Input(id=self._FIELD_IDS["top_k"], placeholder="100")
                top_k_input.value = str(self.default_top_k)
                yield top_k_input
            with VerticalGroup(classes="field-col"):
                yield Static("Specificity-screen candidates:", classes="field-label")
                atk_input = Input(
                    id=self._FIELD_IDS["affinity_top_k"], placeholder="5",
                )
                atk_input.value = str(self.default_affinity_top_k)
                yield atk_input

        # --- Vina options: exhaustiveness + other knobs ---
        yield Static("Vina Options", classes="section-heading")
        with HorizontalGroup():
            with VerticalGroup(classes="field-col"):
                yield Static("Exhaustiveness (8/16/32):", classes="field-label")
                exh_input = Input(
                    id=self._FIELD_IDS["exhaustiveness"], placeholder="8",
                )
                exh_input.value = str(self.default_exhaustiveness)
                yield exh_input
            with VerticalGroup(classes="field-col"):
                yield Static("num_modes (1..20):", classes="field-label")
                nm_input = Input(id=self._FIELD_IDS["num_modes"], placeholder="9")
                nm_input.value = str(self.default_num_modes)
                yield nm_input
        with HorizontalGroup():
            with VerticalGroup(classes="field-col"):
                yield Static("energy_range kcal/mol:", classes="field-label")
                er_input = Input(
                    id=self._FIELD_IDS["energy_range"], placeholder="3.0",
                )
                er_input.value = str(self.default_energy_range)
                yield er_input
            with VerticalGroup(classes="field-col"):
                yield Static("Grid padding \u00c5:", classes="field-label")
                pad_input = Input(
                    id=self._FIELD_IDS["grid_padding_angstrom"],
                    placeholder="4.0",
                )
                pad_input.value = str(self.default_grid_padding_angstrom)
                yield pad_input
        with HorizontalGroup():
            with VerticalGroup(classes="field-col"):
                yield Static("Per-ligand timeout sec:", classes="field-label")
                timeout_input = Input(
                    id=self._FIELD_IDS["per_ligand_timeout_seconds"],
                    placeholder="1800",
                )
                if self.default_per_ligand_timeout_seconds is not None:
                    timeout_input.value = str(self.default_per_ligand_timeout_seconds)
                yield timeout_input
            with VerticalGroup(classes="field-col"):
                yield Static("Time budget hours (advisory):", classes="field-label")
                budget_input = Input(
                    id=self._FIELD_IDS["time_budget_hours"],
                    placeholder="e.g. 4",
                )
                if self.default_time_budget_hours is not None:
                    budget_input.value = str(self.default_time_budget_hours)
                yield budget_input

        # --- Advanced ---
        yield Static("Advanced", classes="section-heading")
        with HorizontalGroup():
            with VerticalGroup(classes="field-col"):
                yield Static("Seed (blank = random):", classes="field-label")
                seed_input = Input(
                    id=self._FIELD_IDS["seed"], placeholder="optional",
                )
                if self.default_seed is not None:
                    seed_input.value = str(self.default_seed)
                yield seed_input
            with VerticalGroup(classes="field-col"):
                pass

        # --- Action buttons ---
        with Horizontal():
            yield Button("Continue", id="btn-dock-plan-continue", variant="primary")
            if not self.confirm_only:
                yield Button("Get LLM Hint", id="btn-dock-plan-llm")

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
        return _machine_info(self.machine_profile)

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
            "affinity_top_k": _int(self._read("affinity_top_k")),
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
            "affinity_top_k": (
                self._read("affinity_top_k") or str(self.default_affinity_top_k)
            ),
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

    def __init__(self, *, top_k: int = 100, moe_available: bool = False, **kwargs) -> None:
        super().__init__(**kwargs)
        self.top_k = top_k
        self.moe_available = moe_available

    def compose(self) -> ComposeResult:
        yield Static("How will the receptor PDBQTs be prepared?", classes="panel-title")
        if self.moe_available:
            help_text = (
                "Each of the top candidates needs its own 3D structure. "
                "Each candidate is predicted via RNAComposer and hydrogens "
                "are added in AutoDockTools. MOE-based processing is also "
                "available."
            )
        else:
            help_text = (
                "Each of the top candidates needs its own 3D structure. "
                "Each candidate is predicted via RNAComposer and hydrogens "
                "are added in AutoDockTools."
            )
        yield Static(help_text, classes="panel-help")
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
            if self.moe_available:
                yield Button(
                    "RNAComposer + MOE (auto)",
                    id="btn-source-rnacomposer-moe",
                    variant="success",
                )
                yield Button(
                    "MOE only (upload RNA PDB)",
                    id="btn-source-moe-manual",
                    variant="primary",
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
        elif event.button.id == "btn-source-rnacomposer-moe":
            self.post_message(
                StructuredActionRequested(Step.DOCKING_SELECTION, "source:rnacomposer-moe")
            )
        elif event.button.id == "btn-source-moe-manual":
            self.post_message(
                StructuredActionRequested(Step.DOCKING_SELECTION, "source:moe-manual")
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
        phase: str = "manual_upload",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.export_dir = export_dir
        self.candidate_ids = candidate_ids
        self.default_structures_dir = default_structures_dir
        self._phase = phase

    def compose(self) -> ComposeResult:
        is_moe = self._phase == "moe_manual_upload"
        yield Static(
            "MOE RNA structure upload" if is_moe else "Manual receptor upload",
            classes="panel-title",
        )
        if is_moe:
            yield Static(
                "Place your RNA PDB files into a directory named after each "
                f"candidate id ({len(self.candidate_ids)} files total) using "
                "the convention [bold]<candidate_id>.pdb[/bold]. "
                "MOE will convert RNA to DNA and minimize with AmberEHT.",
                classes="panel-help",
            )
        else:
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
        if self.export_dir:
            yield Static(f"Sequences exported to: [bold]{self.export_dir}[/bold]")
        yield Static(
            "Path to your RNA structures directory:" if is_moe
            else "Path to your prepared structures directory:"
        )
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
                    {"phase": self._phase, "structures_dir": path},
                )
            )
        elif event.button.id == "btn-manual-back":
            self.post_message(
                StructuredActionRequested(Step.DOCKING_SELECTION, "source:back")
            )


def _bar_markup(current: int, total: int) -> str:
    if total <= 0:
        return ""
    bar = _render_progress_bar(current, total)
    pct = current / total * 100
    return f"[bold]{bar}[/bold] {pct:.0f}%  ({current}/{total})"


class DockingRNAComposerProgressPanel(_BaseStructuredPanel):
    """Phase 3 (auto): show RNAComposer scraping progress + cancel button."""

    DEFAULT_CSS = """
    DockingRNAComposerProgressPanel > .panel-help {
        margin: 1 0;
    }
    DockingRNAComposerProgressPanel > .panel-note {
        color: $text-muted;
        margin-bottom: 0;
    }
    DockingRNAComposerProgressPanel > .progress-bar {
        color: $primary;
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
        fetched: int = 0,
        postprocessed: int = 0,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.total = total
        self.fetched = fetched
        self.postprocessed = postprocessed

    def compose(self) -> ComposeResult:
        yield Static(
            "RNAComposer structure preparation",
            classes="panel-title",
        )
        yield Static(
            "Submitting each candidate sequence to RNAComposer (external server), "
            "converting RNA \u2192 DNA, adding hydrogens, and computing the search "
            "box. This may take a few minutes per candidate. Delays or failures are "
            "possible if the server is slow or unreachable \u2014 you can cancel and "
            "switch to manual upload at any time.",
            classes="panel-help",
        )
        yield Static(
            f"Fetching: {self.fetched} / {self.total} structures received",
            classes="panel-note",
            id="dock-rnacomposer-fetch-progress",
        )
        yield Static(
            _bar_markup(self.fetched, self.total),
            classes="progress-bar",
            id="dock-rnacomposer-fetch-bar",
        )
        yield Static(
            f"Post-processing: {self.postprocessed} / {self.total} converted and minimized",
            classes="panel-note",
            id="dock-rnacomposer-post-progress",
        )
        yield Static(
            _bar_markup(self.postprocessed, self.total),
            classes="progress-bar",
            id="dock-rnacomposer-post-bar",
        )
        with Horizontal():
            yield Button("Cancel", id="btn-rnacomposer-cancel", variant="warning")

    def update_pipeline_progress(
        self,
        *,
        fetched: int,
        postprocessed: int,
        total: int,
        fetching_candidate: str = "",
        fetching_elapsed: float | None = None,
        postprocessing_candidate: str = "",
    ) -> None:
        self.fetched = fetched
        self.postprocessed = postprocessed
        self.total = total
        try:
            fetch_line = f"Fetching: {fetched} / {total} structures received"
            if fetching_candidate:
                fetch_line += f" \u2014 current: {fetching_candidate}"
            if fetching_elapsed is not None:
                fetch_line += f" (waiting {fetching_elapsed:.0f}s)"
            self.query_one("#dock-rnacomposer-fetch-progress", Static).update(fetch_line)
            self.query_one("#dock-rnacomposer-fetch-bar", Static).update(
                _bar_markup(fetched, total)
            )

            post_line = f"Post-processing: {postprocessed} / {total} converted and minimized"
            if postprocessing_candidate:
                post_line += f" \u2014 current: {postprocessing_candidate}"
            self.query_one("#dock-rnacomposer-post-progress", Static).update(post_line)
            self.query_one("#dock-rnacomposer-post-bar", Static).update(
                _bar_markup(postprocessed, total)
            )
        except NoMatches:
            _log.debug("Progress label missing during update", exc_info=True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-rnacomposer-cancel":
            self.post_message(
                StructuredActionRequested(Step.DOCKING_SELECTION, "rnacomposer:cancel")
            )


class DockingMOEProgressPanel(_BaseStructuredPanel):
    """MOE processing status panel with cancel button.

    moebatch processes all candidates in a single batch subprocess.run call,
    so per-file progress is not available.  The panel shows a static status
    message and a cancel button (cancel takes effect after the current batch
    finishes or during the RNAComposer fetch phase if using the combined path).
    """

    DEFAULT_CSS = """
    DockingMOEProgressPanel > .panel-help {
        margin: 1 0;
    }
    DockingMOEProgressPanel > .panel-note {
        color: $text-muted;
        margin-bottom: 1;
    }
    DockingMOEProgressPanel Horizontal {
        height: auto;
    }
    """

    def __init__(
        self,
        *,
        total: int = 0,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.total = total

    def compose(self) -> ComposeResult:
        yield Static(
            "MOE Processing",
            classes="panel-title",
        )
        yield Static(
            f"Running MOE batch processing on {self.total} candidate(s). "
            "MOE processes all structures in a single batch — progress "
            "updates will appear in the chat above. "
            "Cancel takes effect after the current batch completes.",
            classes="panel-help",
        )
        with Horizontal():
            yield Button("Cancel", id="btn-moe-cancel", variant="warning")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-moe-cancel":
            self.post_message(
                StructuredActionRequested(Step.DOCKING_SELECTION, "moe:cancel")
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
            "All parameters were already set in Step 6 / Phase 1. Review the "
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
            f"\u2022 Candidates to dock: [bold]{self.top_k}[/]\n"
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
        return _machine_info(self.machine_profile)

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
