from __future__ import annotations

import itertools

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Label, Static

from aptgent.domain.models import CandidateSequence, Mutation


class EnumerationScreen(Screen):
    """Enumerate candidates from selected sites."""

    def compose(self) -> ComposeResult:
        yield self.app.progress_bar
        yield self.app.status_panel

        with Vertical(id="content-area"):
            yield Static("Step 4: Candidate Enumeration", classes="title")
            yield Static("", id="enum-info")
            yield Static("", id="enum-error", classes="error-text")
            yield Vertical(id="candidate-preview")

        with Horizontal(id="action-bar"):
            yield Button("Back", id="btn-back")
            yield Button("Continue", id="btn-continue", variant="primary", disabled=True)

    def on_mount(self) -> None:
        self._enumerate()

    def _enumerate(self) -> None:
        state = self.app.current_state
        seq: str = state.input_payload.get("initial_sequence", "")
        sites = state.confirmed_mutation_sites
        max_candidates = self.app.config.get("enumeration", {}).get("max_candidates", 5000)

        info = self.query_one("#enum-info", Static)
        error = self.query_one("#enum-error", Static)
        preview = self.query_one("#candidate-preview", Vertical)
        preview.remove_children()

        if not sites:
            error.update("No mutation sites selected. Please go back and select at least one site.")
            return

        if not seq:
            error.update("No sequence available.")
            return

        total = 4 ** len(sites)
        info.update(f"Selected sites: {sites}\nTotal combinations: {total} (max allowed: {max_candidates})")

        if total > max_candidates:
            error.update(
                f"Too many candidates ({total}). Please reduce mutation sites or increase threshold."
            )
            return

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
        self.app.save_state()
        error.update("")

        # Show first few
        preview.mount(Static(f"Generated {len(candidates)} candidates. First 5 preview:"))
        for c in candidates[:5]:
            mut_str = ", ".join(f"{m.position}:{m.original}>{m.mutated}" for m in c.mutations)
            preview.mount(Label(f"{c.candidate_id} | {c.sequence[:40]}... | edits: {mut_str}"))

        self.query_one("#btn-continue", Button).disabled = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-continue":
            self.app.advance_step()
        elif event.button.id == "btn-back":
            self.app.pop_screen()
