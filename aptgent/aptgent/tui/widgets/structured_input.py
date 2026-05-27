from __future__ import annotations

import logging

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.message import Message
from textual.widgets import Button, Input, OptionList, SelectionList, Static
from textual.widgets.option_list import Option

from aptgent.domain.enums import Step

_log = logging.getLogger(__name__)


class StructuredInputSubmitted(Message):
    """Posted by structured input panels when the user submits."""

    def __init__(self, step: Step, data: dict) -> None:
        super().__init__()
        self.step = step
        self.data = data


class StructuredActionRequested(Message):
    """Posted by structured input panels for button or option actions."""

    def __init__(self, step: Step, action: str) -> None:
        super().__init__()
        self.step = step
        self.action = action


class _BaseStructuredPanel(Vertical):
    """Shared chrome for structured input panels.

    Each panel subclass inherits this base to avoid repeating the surface/
    border/padding block and the common ``.panel-title`` / ``.panel-help``
    typography.
    """

    DEFAULT_CSS = """
    _BaseStructuredPanel {
        background: $surface-darken-2;
        border: round $primary;
        padding: 1 2;
        margin: 1 0;
        width: 95%;
        height: auto;
    }
    _BaseStructuredPanel > .panel-title {
        text-style: bold;
        margin-bottom: 1;
    }
    _BaseStructuredPanel > .panel-help {
        color: $text-muted;
        margin-bottom: 1;
    }
    """


class ActionMenuPanel(_BaseStructuredPanel):
    """Keyboard-first action chooser for a workflow step."""

    DEFAULT_CSS = """
    ActionMenuPanel > OptionList {
        height: auto;
        max-height: 10;
        border: tall $surface-lighten-1;
    }
    ActionMenuPanel.expanded-menu > OptionList {
        max-height: 22;
    }
    """

    def __init__(
        self,
        step: Step,
        title: str,
        choices: list[tuple[str, str, str]],
        *,
        help_text: str = "Use Up/Down to choose and Enter to confirm.",
        expanded: bool = False,
        **kwargs,
    ) -> None:
        if expanded:
            classes = kwargs.get("classes")
            kwargs["classes"] = (
                f"{classes} expanded-menu" if classes else "expanded-menu"
            )
        super().__init__(**kwargs)
        self.step = step
        self.title = title
        self.choices = choices
        self.help_text = help_text

    def compose(self) -> ComposeResult:
        yield Static(self.title, classes="panel-title")
        yield Static(self.help_text, classes="panel-help")
        options = [
            Option(
                f"[bold]{label}[/bold]\n[dim]{description}[/dim]",
                id=action,
            )
            for action, label, description in self.choices
        ]
        yield OptionList(*options, id="action-menu")

    def on_mount(self) -> None:
        try:
            self.query_one("#action-menu", OptionList).focus()
        except NoMatches:
            _log.debug("Focus target missing during on_mount", exc_info=True)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        option_id = event.option.id
        if option_id:
            self.post_message(StructuredActionRequested(self.step, option_id))


class MutationSitePanel(_BaseStructuredPanel):
    """Keyboard-friendly mutation-site selector."""

    DEFAULT_CSS = """
    MutationSitePanel {
        height: 22;
        max-height: 24;
    }
    MutationSitePanel > SelectionList {
        height: 1fr;
        min-height: 8;
        border: tall $surface-lighten-1;
    }
    MutationSitePanel > Button {
        margin-top: 1;
        width: 100%;
    }
    """

    def __init__(self, sequence: str, proposed_sites: list[int], **kwargs) -> None:
        super().__init__(**kwargs)
        self.sequence = sequence
        self.proposed_sites = proposed_sites
        self.selection_list: SelectionList[int] | None = None

    def compose(self) -> ComposeResult:
        yield Static("Select mutation sites", classes="panel-title")
        yield Static(
            "Use Up/Down to move, Space to toggle, Enter to confirm.",
            classes="panel-help",
        )
        selections = [
            (
                f"[bold]{pos}[/bold] ({base}){' [green]recommended[/green]' if pos in self.proposed_sites else ''}",
                pos,
                pos in self.proposed_sites,
            )
            for pos, base in enumerate(self.sequence)
        ]
        self.selection_list = SelectionList(*selections, id="site-selection-list")
        yield self.selection_list
        yield Button("Confirm Selection", id="btn-confirm-sites", variant="success")

    def on_mount(self) -> None:
        if self.selection_list is not None:
            self.selection_list.focus()
        self.set_timer(0.05, self._deferred_focus)

    def _deferred_focus(self) -> None:
        if self.selection_list is not None:
            self.selection_list.focus()

    def get_selected(self) -> list[int]:
        if self.selection_list is None:
            return []
        return sorted(int(value) for value in self.selection_list.selected)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-confirm-sites":
            self.post_message(
                StructuredInputSubmitted(
                    Step.SITE_PROPOSAL,
                    {"selected_sites": self.get_selected()},
                )
            )

    def on_selection_list_selected_changed(self, event: SelectionList.SelectedChanged) -> None:
        event.stop()


class AnalogCheckboxPanel(_BaseStructuredPanel):
    """Checkbox panel for toggling individual recommended analogs."""

    DEFAULT_CSS = """
    AnalogCheckboxPanel > SelectionList {
        height: auto;
        max-height: 12;
        border: tall $surface-lighten-1;
    }
    AnalogCheckboxPanel > Button {
        margin-top: 1;
        width: 100%;
    }
    """

    def __init__(
        self,
        analog_names: list[str],
        *,
        target_name: str = "",
        title: str = "Select Analogs for Specificity Filter",
        help_text: str = "Use Up/Down to move, Space to toggle, Enter to confirm.",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.analog_names = analog_names
        self.target_name = target_name
        self.title = title
        self.help_text = help_text
        self.selection_list: SelectionList[str] | None = None
        self.confirm_button: Button | None = None

    def compose(self) -> ComposeResult:
        yield Static(self.title, classes="panel-title")
        if self.target_name:
            yield Static(f"Target: [bold]{self.target_name}[/]")
        yield Static(self.help_text, classes="panel-help")
        selections = [
            (f"[bold]{name}[/bold]", name, True)
            for name in self.analog_names
        ]
        self.selection_list = SelectionList(*selections, id="analog-selection-list")
        yield self.selection_list
        self.confirm_button = Button(
            "Confirm Selection",
            id="btn-confirm-analogs",
            variant="success",
        )
        yield self.confirm_button

    def on_mount(self) -> None:
        if self.selection_list is not None:
            self.selection_list.focus()

    def on_selection_list_selected_changed(self, event: SelectionList.SelectedChanged) -> None:
        event.stop()
        if self.confirm_button is not None and self.selection_list is not None:
            self.confirm_button.disabled = not self.selection_list.selected

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-confirm-analogs" and self.selection_list is not None:
            selected = ", ".join(self.selection_list.selected)
            self.post_message(
                StructuredInputSubmitted(
                    Step.SPECIFICITY_FILTER,
                    {"action": "run", "analogs_text": selected},
                )
            )


class PdbSelectionPanel(_BaseStructuredPanel):
    """Select a chain and optional ligand from a parsed PDB structure."""

    DEFAULT_CSS = """
    PdbSelectionPanel > .panel-help {
        margin: 1 0;
    }
    PdbSelectionPanel > .panel-section {
        margin-top: 1;
        text-style: bold;
    }
    PdbSelectionPanel > OptionList {
        height: auto;
        max-height: 8;
        border: tall $surface-lighten-1;
        margin-bottom: 1;
    }
    PdbSelectionPanel Horizontal {
        height: auto;
    }
    PdbSelectionPanel Horizontal > Button {
        margin-right: 1;
    }
    """

    def __init__(
        self,
        *,
        chain_choices: list[tuple[str, str, str]],
        ligand_choices: list[tuple[str, str, str]] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.chain_choices = chain_choices
        self.ligand_choices = ligand_choices or []

    def compose(self) -> ComposeResult:
        yield Static("PDB Import Review", classes="panel-title")
        yield Static(
            "Select which nucleic-acid chain and ligand should be used for this workflow.",
            classes="panel-help",
        )
        yield Static("Chain candidates", classes="panel-section")
        yield OptionList(
            *[
                Option(
                    f"[bold]{label}[/bold]\n[dim]{description}[/dim]",
                    id=value,
                )
                for value, label, description in self.chain_choices
            ],
            id="pdb-chain-menu",
        )
        if self.ligand_choices:
            yield Static("Ligand candidates", classes="panel-section")
            yield OptionList(
                *[
                    Option(
                        f"[bold]{label}[/bold]\n[dim]{description}[/dim]",
                        id=value,
                    )
                    for value, label, description in self.ligand_choices
                ],
                id="pdb-ligand-menu",
            )
        with Horizontal():
            yield Button("Use Selection", id="btn-confirm-pdb-selection", variant="success")
            yield Button("Re-enter Intake", id="btn-restart-pdb-selection")

    def on_mount(self) -> None:
        try:
            self.query_one("#pdb-chain-menu", OptionList).focus()
        except NoMatches:
            _log.debug("Focus target missing during on_mount", exc_info=True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-confirm-pdb-selection":
            chain_menu = self.query_one("#pdb-chain-menu", OptionList)
            if chain_menu.option_count == 0:
                return
            chain_index = chain_menu.highlighted if chain_menu.highlighted is not None else 0
            chain_option = chain_menu.get_option_at_index(chain_index)
            ligand_key = None
            if self.ligand_choices:
                ligand_menu = self.query_one("#pdb-ligand-menu", OptionList)
                if ligand_menu.option_count == 0:
                    return
                ligand_index = (
                    ligand_menu.highlighted if ligand_menu.highlighted is not None else 0
                )
                ligand_option = ligand_menu.get_option_at_index(ligand_index)
                ligand_key = ligand_option.id
            self.post_message(
                StructuredInputSubmitted(
                    Step.INTAKE,
                    {
                        "action": "confirm_pdb_selection",
                        "chain_id": chain_option.id,
                        "ligand_key": ligand_key,
                    },
                )
            )
        elif event.button.id == "btn-restart-pdb-selection":
            self.post_message(
                StructuredActionRequested(
                    Step.INTAKE,
                    "restart-pdb-selection",
                )
            )


class SpecificityPanel(_BaseStructuredPanel):
    """Inline widget for specificity filter input."""

    DEFAULT_CSS = """
    SpecificityPanel > .panel-help {
        margin: 1 0;
    }
    SpecificityPanel > Input {
        margin: 1 0;
    }
    SpecificityPanel Horizontal {
        height: auto;
    }
    SpecificityPanel Horizontal > Button {
        margin-right: 1;
    }
    """

    def __init__(
        self,
        target_name: str = "",
        analogs_text: str = "",
        *,
        title: str = "Specificity Filter",
        help_text: str = "Enter analog molecules for cross-screening. Use commas between names or SMILES.",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.target_name = target_name
        self.analogs_text = analogs_text
        self.title = title
        self.help_text = help_text

    def compose(self) -> ComposeResult:
        yield Static(self.title, classes="panel-title")
        if self.target_name:
            yield Static(f"Target: [bold]{self.target_name}[/]")
        yield Static(self.help_text, classes="panel-help")
        analog_input = Input(
            id="analog-input",
            placeholder="e.g. adenine, hypoxanthine",
        )
        analog_input.value = self.analogs_text
        yield analog_input
        with Horizontal():
            yield Button("Run Filter", id="btn-run-filter", variant="warning")
            yield Button("Skip", id="btn-skip-filter")

    def on_mount(self) -> None:
        try:
            self.query_one("#analog-input", Input).focus()
        except NoMatches:
            _log.debug("Focus target missing during on_mount", exc_info=True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "btn-run-filter":
            analogs = self.query_one("#analog-input", Input).value.strip()
            self.post_message(
                StructuredInputSubmitted(
                    Step.SPECIFICITY_FILTER,
                    {"action": "run", "analogs_text": analogs},
                )
            )
        elif btn_id == "btn-skip-filter":
            self.post_message(
                StructuredInputSubmitted(
                    Step.SPECIFICITY_FILTER,
                    {"action": "skip"},
                )
            )


class AnalogCustomPanel(_BaseStructuredPanel):
    """Natural-language analog entry with LLM parsing and confirmation."""

    DEFAULT_CSS = """
    AnalogCustomPanel > .panel-help {
        margin: 1 0;
    }
    AnalogCustomPanel > Input {
        margin: 1 0;
    }
    AnalogCustomPanel Horizontal {
        height: auto;
    }
    AnalogCustomPanel Horizontal > Button {
        margin-right: 1;
    }
    AnalogCustomPanel > .resolved-list {
        margin: 1 0;
    }
    """

    def __init__(
        self,
        *,
        target_name: str = "",
        title: str = "Custom Specificity Analogs",
        help_text: str = "Describe the analogs you want in natural language.",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.target_name = target_name
        self.title = title
        self.help_text = help_text
        self._resolved_analogs_text: str = ""
        self._resolved_pairs: list[tuple[str, bool]] = []

    def compose(self) -> ComposeResult:
        yield Static(self.title, classes="panel-title")
        if self.target_name:
            yield Static(f"Target: [bold]{self.target_name}[/]")
        yield Static(self.help_text, classes="panel-help")
        yield Input(
            id="custom-analog-input",
            placeholder="e.g. just caffeine is fine",
        )
        with Horizontal():
            yield Button("Parse My Request", id="btn-parse-custom", variant="primary")
            yield Button("Skip", id="btn-skip-custom")

    def on_mount(self) -> None:
        try:
            self.query_one("#custom-analog-input", Input).focus()
        except NoMatches:
            _log.debug("Focus target missing during on_mount", exc_info=True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "btn-parse-custom":
            text = self.query_one("#custom-analog-input", Input).value.strip()
            self.post_message(
                StructuredInputSubmitted(
                    Step.SPECIFICITY_FILTER,
                    {"action": "parse_custom", "custom_text": text},
                )
            )
        elif btn_id == "btn-skip-custom":
            self.post_message(
                StructuredInputSubmitted(
                    Step.SPECIFICITY_FILTER,
                    {"action": "skip"},
                )
            )
        elif btn_id == "btn-confirm-custom":
            self.post_message(
                StructuredInputSubmitted(
                    Step.SPECIFICITY_FILTER,
                    {"action": "run", "analogs_text": self._resolved_analogs_text},
                )
            )
        elif btn_id == "btn-retry-custom":
            self._reset_to_input_mode()

    def show_confirmation(self, resolved_pairs: list[tuple[str, bool]]) -> None:
        self._resolved_pairs = resolved_pairs
        resolved_names = [name for name, ok in resolved_pairs if ok]
        self._resolved_analogs_text = ", ".join(resolved_names)

        for child in list(self.children):
            child.remove()

        self.mount(Static("Parsed Analogs", classes="panel-title"))
        lines: list[str] = []
        for name, ok in resolved_pairs:
            if ok:
                lines.append(f"  [green]\u2713[/green] {name}")
            else:
                lines.append(f"  [red]\u2717[/red] {name} (could not resolve)")
        if lines:
            self.mount(Static("\n".join(lines), classes="resolved-list"))
        with Horizontal():
            self.mount(Button("Confirm and Run", id="btn-confirm-custom", variant="success"))
            self.mount(Button("Try Again", id="btn-retry-custom"))
        try:
            self.query_one("#btn-confirm-custom", Button).focus()
        except NoMatches:
            _log.debug("Focus target missing after confirmation mount", exc_info=True)

    def _reset_to_input_mode(self) -> None:
        self._resolved_pairs = []
        self._resolved_analogs_text = ""
        for child in list(self.children):
            child.remove()

        self.mount(Static(self.title, classes="panel-title"))
        if self.target_name:
            self.mount(Static(f"Target: [bold]{self.target_name}[/]"))
        self.mount(Static(self.help_text, classes="panel-help"))
        self.mount(Input(
            id="custom-analog-input",
            placeholder="e.g. just caffeine is fine",
        ))
        with Horizontal():
            self.mount(Button("Parse My Request", id="btn-parse-custom", variant="primary"))
            self.mount(Button("Skip", id="btn-skip-custom"))
        try:
            self.query_one("#custom-analog-input", Input).focus()
        except NoMatches:
            _log.debug("Focus target missing after retry mount", exc_info=True)


class DockingStrategyPanel(_BaseStructuredPanel):
    """Phase 1: pick top-K + optional time budget, or skip docking.

    The top candidates are docked individually; default top-k is 5.
    """

    DEFAULT_CSS = """
    DockingStrategyPanel > .panel-help {
        margin: 1 0;
    }
    DockingStrategyPanel > Input {
        margin: 1 0;
    }
    DockingStrategyPanel Horizontal {
        height: auto;
    }
    DockingStrategyPanel Horizontal > Button {
        margin-right: 1;
    }
    """

    def __init__(
        self,
        *,
        machine_profile: dict | None = None,
        time_budget: int | None = None,
        candidate_count: int = 0,
        default_top_k: int = 5,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.machine_profile = machine_profile or {}
        self.time_budget = time_budget
        self.candidate_count = candidate_count
        self.default_top_k = max(1, min(default_top_k, candidate_count or default_top_k))

    def compose(self) -> ComposeResult:
        yield Static("Docking Selection \u2014 Step 7", classes="panel-title")
        yield Static(
            "Choose how many top candidates to dock (paper default: top 5). "
            "Each candidate gets its own 3D structure prepared in the next step.",
            classes="panel-help",
        )
        yield Static(f"[dim]{self._machine_info()}[/]")
        yield Static(f"Available candidates: [bold]{self.candidate_count}[/bold]")
        yield Static("Top-K candidates to dock:")
        top_k_input = Input(id="dock-plan-top-k", placeholder="5")
        top_k_input.value = str(self.default_top_k)
        yield top_k_input
        yield Static("Optional time budget (hours):")
        budget_input = Input(id="dock-plan-budget", placeholder="e.g. 4")
        if self.time_budget is not None:
            budget_input.value = str(self.time_budget)
        yield budget_input
        with Horizontal():
            yield Button("Continue", id="btn-dock-plan-continue", variant="primary")
            yield Button("Get LLM Hint", id="btn-dock-plan-llm")
            yield Button("Skip Docking", id="btn-dock-plan-skip", variant="warning")

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
            self.query_one("#dock-plan-top-k", Input).focus()
        except NoMatches:
            _log.debug("Focus target missing during on_mount", exc_info=True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        budget = self.query_one("#dock-plan-budget", Input).value.strip()
        top_k = self.query_one("#dock-plan-top-k", Input).value.strip() or str(self.default_top_k)
        if event.button.id == "btn-dock-plan-continue":
            self.post_message(
                StructuredInputSubmitted(
                    Step.DOCKING_SELECTION,
                    {
                        "phase": "topk_selected",
                        "top_k": top_k,
                        "time_budget": budget,
                    },
                )
            )
        elif event.button.id == "btn-dock-plan-llm":
            self.post_message(
                StructuredActionRequested(
                    Step.DOCKING_SELECTION,
                    f"llm-hint:{top_k}:{budget}",
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
    """Final docking parameter confirmation.

    Shows the per-candidate receptor + box overview (computed deterministically
    upstream), lets the user tweak the global exhaustiveness and box padding,
    and offers a "Cover whole aptamer" button that re-derives every box from
    the receptor geometry.
    """

    DEFAULT_CSS = """
    DockingParamPanel > .panel-help {
        margin: 1 0;
    }
    DockingParamPanel > .panel-note {
        color: $text-muted;
        margin-bottom: 1;
    }
    DockingParamPanel > Input {
        margin-bottom: 1;
    }
    DockingParamPanel Horizontal {
        height: auto;
    }
    DockingParamPanel Horizontal > Input {
        width: 1fr;
        margin-right: 1;
    }
    DockingParamPanel > Button {
        margin-top: 1;
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

    def compose(self) -> ComposeResult:
        yield Static("Docking Configuration", classes="panel-title")
        yield Static(
            "AutoDock Vina with default num_modes (9) and energy_range (3.0); "
            "each candidate uses its own receptor PDBQT and a search box that "
            "covers the whole aptamer.",
            classes="panel-help",
        )
        if self.recommendation_reason:
            yield Static(self.recommendation_reason, classes="panel-note")
        yield Static(f"[dim]{self._machine_info()}[/]")

        yield Static("Time budget (hours):")
        budget_input = Input(id="dock-time-budget", placeholder="e.g. 4")
        if self.time_budget is not None:
            budget_input.value = str(self.time_budget)
        yield budget_input

        yield Static(f"Per-receptor structures ({len(self.receptor_paths)} loaded)")
        yield Static(self._receptor_summary(), classes="receptor-summary")

        yield Static("Exhaustiveness (Vina default 8; 16/32 if compute is generous):")
        exh_input = Input(id="dock-exhaustiveness", placeholder="8")
        exh_input.value = str(self.recommended_exhaustiveness)
        yield exh_input

        yield Static("Grid padding (\u00c5):")
        pad_input = Input(id="dock-padding", placeholder="4.0")
        pad_input.value = str(self.grid_padding_angstrom)
        yield pad_input

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
            self.query_one("#dock-time-budget", Input).focus()
        except NoMatches:
            _log.debug("Focus target missing during on_mount", exc_info=True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-submit-dock":
            data = self._collect_data()
            self.post_message(
                StructuredInputSubmitted(Step.DOCKING_SELECTION, data)
            )
        elif event.button.id == "btn-cover-aptamer":
            try:
                padding = float(self.query_one("#dock-padding", Input).value.strip() or "4.0")
            except (ValueError, AttributeError):
                padding = self.grid_padding_angstrom
            self.post_message(
                StructuredActionRequested(
                    Step.DOCKING_SELECTION,
                    f"cover-aptamer:{padding}",
                )
            )

    def _collect_data(self) -> dict:
        def iv(widget_id: str) -> int | None:
            try:
                return int(self.query_one(f"#{widget_id}", Input).value.strip())
            except (ValueError, AttributeError):
                return None

        def fv(widget_id: str) -> float | None:
            try:
                return float(self.query_one(f"#{widget_id}", Input).value.strip())
            except (ValueError, AttributeError):
                return None

        budget_str = self.query_one("#dock-time-budget", Input).value.strip()
        exh_raw = iv("dock-exhaustiveness")
        if exh_raw is None or exh_raw < 1:
            exh_raw = self.recommended_exhaustiveness
        padding = fv("dock-padding") or self.grid_padding_angstrom

        return {
            "phase": "param_submitted",
            "time_budget": int(budget_str) if budget_str.isdigit() else self.time_budget,
            "exhaustiveness": exh_raw,
            "grid_padding_angstrom": padding,
            "recommendation_reason": self.recommendation_reason,
            "uses_recommendation": self.mode == "llm",
            "accepted_recommendation": self.accepted_recommendation,
        }
