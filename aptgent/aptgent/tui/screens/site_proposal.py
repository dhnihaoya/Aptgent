from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Checkbox, Input, Label, Static, TextArea

from aptgent.llm.skills import SiteProposalSkill


class SiteProposalScreen(Screen):
    """Propose, confirm, or override mutation sites."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.skill = SiteProposalSkill()
        self.checkboxes: list[Checkbox] = []

    def compose(self) -> ComposeResult:
        yield self.app.progress_bar
        yield self.app.status_panel

        with Vertical(id="content-area"):
            yield Static("Step 3: Mutation Site Proposal", classes="title")
            yield Static("Proposed sites (check = selected):", classes="info-text")
            yield Vertical(id="sites-list")
            yield Static("", id="site-reasoning", classes="info-text")
            yield Static("---", classes="info-text")
            yield Static("Or describe changes in natural language:", classes="info-text")
            yield TextArea(id="rephrase-input", text="")

        with Horizontal(id="action-bar"):
            yield Button("Accept Recommended", id="btn-accept", variant="success")
            yield Button("Apply Rephrase", id="btn-rephrase", variant="primary")
            yield Button("Back", id="btn-back")
            yield Button("Continue", id="btn-continue", variant="primary")

    def on_mount(self) -> None:
        self._generate_proposal()

    def _generate_proposal(self) -> None:
        state = self.app.current_state
        seq = state.input_payload.get("initial_sequence", "")
        struct = state.secondary_structure
        container = self.query_one("#sites-list", Vertical)
        container.remove_children()
        self.checkboxes = []

        if struct is None:
            return

        try:
            result = self.skill.propose(seq, struct)
        except Exception as e:
            self.query_one("#site-reasoning", Static).update(f"LLM error: {e}")
            return

        sites = result.get("proposed_sites", [])
        reasoning = result.get("reasoning", "")
        self.query_one("#site-reasoning", Static).update(f"Reasoning: {reasoning}")

        for pos in range(len(seq)):
            cb = Checkbox(f"Position {pos} ({seq[pos]})", value=(pos in sites))
            self.checkboxes.append(cb)
            container.mount(cb)

    def _selected_sites(self) -> list[int]:
        return [i for i, cb in enumerate(self.checkboxes) if cb.value]

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        state = self.app.current_state

        if btn_id == "btn-accept":
            state.confirmed_mutation_sites = self._selected_sites()
            self.app.save_state()
            self.app.advance_step()

        elif btn_id == "btn-rephrase":
            text = self.query_one("#rephrase-input", TextArea).text.strip()
            if not text:
                return
            seq = state.input_payload.get("initial_sequence", "")
            try:
                result = self.skill.rephrase(seq, text)
            except Exception as e:
                self.query_one("#site-reasoning", Static).update(f"LLM error: {e}")
                return
            sites = result.get("proposed_sites", [])
            for i, cb in enumerate(self.checkboxes):
                cb.value = (i in sites)
            reasoning = result.get("reasoning", "")
            self.query_one("#site-reasoning", Static).update(f"Rephrased reasoning: {reasoning}")

        elif btn_id == "btn-continue":
            state.confirmed_mutation_sites = self._selected_sites()
            self.app.save_state()
            self.app.advance_step()

        elif btn_id == "btn-back":
            self.app.pop_screen()
