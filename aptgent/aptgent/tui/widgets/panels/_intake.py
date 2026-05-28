from __future__ import annotations

import logging

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.css.query import NoMatches
from textual.widgets import Button, OptionList, SelectionList, Static
from textual.widgets.option_list import Option

from aptgent.domain.enums import Step

from ._core import StructuredActionRequested, StructuredInputSubmitted, _BaseStructuredPanel

_log = logging.getLogger(__name__)


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
            if not self.get_selected():
                self.app.notify("Please select at least one mutation site.")
                return
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
