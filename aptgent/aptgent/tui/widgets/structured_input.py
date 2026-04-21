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
    """

    def __init__(
        self,
        step: Step,
        title: str,
        choices: list[tuple[str, str, str]],
        *,
        help_text: str = "Use Up/Down to choose and Enter to confirm.",
        **kwargs,
    ) -> None:
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


class DockingStrategyPanel(_BaseStructuredPanel):
    """Initial planner for docking strategy and optional time budget."""

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
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.machine_profile = machine_profile or {}
        self.time_budget = time_budget

    def compose(self) -> ComposeResult:
        yield Static("Docking Planning", classes="panel-title")
        yield Static(
            "If you already know your parameter plan, open the manual form. "
            "If not, you can optionally enter a time budget first and let the LLM draft the docking settings.",
            classes="panel-help",
        )
        yield Static(f"[dim]{self._machine_info()}[/]")
        yield Static("Optional time budget (hours):")
        budget_input = Input(id="dock-plan-budget", placeholder="e.g. 4")
        if self.time_budget is not None:
            budget_input.value = str(self.time_budget)
        yield budget_input
        with Horizontal():
            yield Button("Get LLM Draft", id="btn-dock-plan-llm", variant="primary")
            yield Button("Use My Own Parameters", id="btn-dock-plan-manual", variant="warning")
            yield Button("Skip Docking", id="btn-dock-plan-skip")

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
            self.query_one("#dock-plan-budget", Input).focus()
        except NoMatches:
            _log.debug("Focus target missing during on_mount", exc_info=True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        budget = self.query_one("#dock-plan-budget", Input).value.strip()
        if event.button.id == "btn-dock-plan-llm":
            self.post_message(
                StructuredActionRequested(
                    Step.DOCKING_SELECTION,
                    f"strategy:llm:{budget}",
                )
            )
        elif event.button.id == "btn-dock-plan-manual":
            self.post_message(
                StructuredActionRequested(
                    Step.DOCKING_SELECTION,
                    f"strategy:manual:{budget}",
                )
            )
        elif event.button.id == "btn-dock-plan-skip":
            self.post_message(
                StructuredActionRequested(
                    Step.DOCKING_SELECTION,
                    "strategy:skip",
                )
            )


class DockingParamPanel(_BaseStructuredPanel):
    """Inline widget for docking configuration parameters."""

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
    """

    def __init__(
        self,
        *,
        mode: str = "manual",
        machine_profile: dict | None = None,
        time_budget: int | None = None,
        recommended_top_k: int = 0,
        recommended_grid_size: list[float] | None = None,
        recommendation_reason: str = "",
        receptor_path_note: str = "",
        grid_center_note: str = "",
        accepted_recommendation: bool = False,
        receptor_path: str | None = None,
        grid_center: list[float] | None = None,
        grid_size: list[float] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.mode = mode
        self.machine_profile = machine_profile or {}
        self.time_budget = time_budget
        self.recommended_top_k = recommended_top_k
        self.recommended_grid_size = recommended_grid_size or []
        self.recommendation_reason = recommendation_reason
        self.receptor_path_note = receptor_path_note
        self.grid_center_note = grid_center_note
        self.accepted_recommendation = accepted_recommendation
        self.receptor_path = receptor_path or ""
        self.grid_center = grid_center or []
        self.grid_size = grid_size or []

    def compose(self) -> ComposeResult:
        yield Static("Docking Configuration", classes="panel-title")
        if self.mode == "llm":
            yield Static(
                "An LLM draft has been loaded. Review the suggested values, then confirm the tertiary-structure receptor path and grid center before continuing.",
                classes="panel-help",
            )
            yield Static(
                (
                    f"Draft source: [bold]{'accepted recommendation' if self.accepted_recommendation else 'editable recommendation'}[/bold]\n"
                    f"Reason: {self.recommendation_reason or 'Resource-balanced docking draft.'}"
                ),
                classes="panel-note",
            )
        else:
            yield Static(
                "Set the docking time budget, batch size, and receptor/grid parameters manually.",
                classes="panel-help",
            )
        yield Static(f"[dim]{self._machine_info()}[/]")
        yield Static("Time budget (hours):")
        budget_input = Input(id="dock-time-budget", placeholder="e.g. 4")
        if self.time_budget is not None:
            budget_input.value = str(self.time_budget)
        yield budget_input
        yield Static("Top-k candidates to dock:")
        top_k_input = Input(id="dock-top-k", placeholder="e.g. 10")
        if self.recommended_top_k > 0:
            top_k_input.value = str(self.recommended_top_k)
        yield top_k_input
        yield Static("Receptor PDBQT file path (prepared or downloaded):")
        if self.mode == "llm" and self.receptor_path_note:
            yield Static(f"[dim]{self.receptor_path_note}[/]", classes="panel-note")
        receptor_input = Input(id="dock-receptor", placeholder="/path/to/receptor.pdbqt")
        receptor_input.value = self.receptor_path
        yield receptor_input
        yield Static("Grid box center (x, y, z):")
        if self.mode == "llm" and self.grid_center_note:
            yield Static(f"[dim]{self.grid_center_note}[/]", classes="panel-note")
        with Horizontal():
            cx_input = Input(id="dock-cx", placeholder="0.0")
            cy_input = Input(id="dock-cy", placeholder="0.0")
            cz_input = Input(id="dock-cz", placeholder="0.0")
            if len(self.grid_center) == 3:
                cx_input.value = str(self.grid_center[0])
                cy_input.value = str(self.grid_center[1])
                cz_input.value = str(self.grid_center[2])
            yield cx_input
            yield cy_input
            yield cz_input
        yield Static("Grid box size (x, y, z):")
        with Horizontal():
            sx_input = Input(id="dock-sx", placeholder="20.0")
            sy_input = Input(id="dock-sy", placeholder="20.0")
            sz_input = Input(id="dock-sz", placeholder="20.0")
            size_values = self.grid_size or self.recommended_grid_size
            if len(size_values) == 3:
                sx_input.value = str(size_values[0])
                sy_input.value = str(size_values[1])
                sz_input.value = str(size_values[2])
            yield sx_input
            yield sy_input
            yield sz_input
        yield Button("Submit & Continue", id="btn-submit-dock", variant="success")

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
            focus_id = "#dock-receptor" if self.mode == "llm" else "#dock-time-budget"
            self.query_one(focus_id, Input).focus()
        except NoMatches:
            _log.debug("Focus target missing during on_mount", exc_info=True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-submit-dock":
            data = self._collect_data()
            self.post_message(
                StructuredInputSubmitted(Step.DOCKING_SELECTION, data)
            )

    def _collect_data(self) -> dict:
        def fv(widget_id: str) -> float | None:
            try:
                return float(self.query_one(f"#{widget_id}", Input).value.strip())
            except (ValueError, AttributeError):
                return None

        cx, cy, cz = fv("dock-cx"), fv("dock-cy"), fv("dock-cz")
        sx, sy, sz = fv("dock-sx"), fv("dock-sy"), fv("dock-sz")

        budget_str = ""
        top_k_str = ""
        budget_str = self.query_one("#dock-time-budget", Input).value.strip()
        top_k_str = self.query_one("#dock-top-k", Input).value.strip()
        receptor = self.query_one("#dock-receptor", Input).value.strip()

        return {
            "time_budget": int(budget_str) if budget_str.isdigit() else self.time_budget,
            "top_k": int(top_k_str) if top_k_str.isdigit() else self.recommended_top_k,
            "receptor_path": receptor or None,
            "grid_center": [cx, cy, cz] if all(v is not None for v in (cx, cy, cz)) else None,
            "grid_size": [sx, sy, sz] if all(v is not None for v in (sx, sy, sz)) else None,
            "recommendation_reason": self.recommendation_reason,
            "uses_recommendation": self.mode == "llm",
            "accepted_recommendation": self.accepted_recommendation,
        }
