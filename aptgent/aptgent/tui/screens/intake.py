from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Input, Label, Static, TextArea

from aptgent.domain.enums import Status, Step
from aptgent.domain.models import TargetMolecule
from aptgent.llm.skills import IntakeSkill


class IntakeScreen(Screen):
    """Collect natural language input and resolve target molecule."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.skill = IntakeSkill()

    def compose(self) -> ComposeResult:
        yield self.app.progress_bar
        yield self.app.status_panel

        with Vertical(id="content-area"):
            yield Static("Step 1: Intake", classes="title")
            yield Static(
                "Describe your aptamer design task. Include the aptamer sequence, "
                "target small molecule (name or SMILES), and any preferences.",
                classes="info-text",
            )
            yield TextArea(id="intake-input", text="")
            yield Static("", id="intake-message", classes="warning-text")

        with Horizontal(id="action-bar"):
            yield Button("Submit", id="btn-submit", variant="primary")
            yield Button("Continue", id="btn-continue", variant="success", disabled=True)

    def on_mount(self) -> None:
        state = self.app.current_state
        if state.input_payload.get("user_text"):
            self.query_one("#intake-input", TextArea).text = state.input_payload["user_text"]
        self._update_for_state()

    def _update_for_state(self) -> None:
        state = self.app.current_state
        msg = self.query_one("#intake-message", Static)
        cont = self.query_one("#btn-continue", Button)

        if state.status == Status.PAUSED and state.pending_input:
            reason = state.pending_input.get("reason", "")
            msg.update(f"Paused: {reason}")
            cont.disabled = False
        elif state.target_molecule and state.input_payload.get("initial_sequence"):
            msg.update("All required fields collected. Ready to continue.")
            cont.disabled = False
        else:
            msg.update("")
            cont.disabled = True

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-submit":
            await self._handle_submit()
        elif event.button.id == "btn-continue":
            self.app.advance_step()

    async def _handle_submit(self) -> None:
        text = self.query_one("#intake-input", TextArea).text.strip()
        if not text:
            self.query_one("#intake-message", Static).update("Please enter a description.")
            return

        self.query_one("#intake-message", Static).update("Processing with LLM...")
        try:
            result = self.skill.extract(text)
        except Exception as e:
            self.query_one("#intake-message", Static).update(f"LLM error: {e}")
            return

        state = self.app.current_state
        state.input_payload["user_text"] = text
        state.input_payload["llm_extracted"] = result

        # Sequence is mandatory
        seq = result.get("initial_sequence")
        if seq:
            state.input_payload["initial_sequence"] = seq
        else:
            follow_up = result.get("follow_up_question", "Please provide the aptamer sequence.")
            self.query_one("#intake-message", Static).update(f"Missing sequence. {follow_up}")
            self.app.save_state()
            return

        # Target molecule
        target_text = result.get("target_molecule")
        if target_text:
            resolved = self.app.molecule_resolver.resolve(target_text)
            if resolved.resolution_status == "resolved":
                state.target_molecule = resolved
            else:
                # Pause for manual molecule input
                state.target_molecule = TargetMolecule(input_text=target_text)
                self.app.engine.pause(state, reason=f"Could not resolve molecule: {target_text}")
                self.query_one("#intake-message", Static).update(
                    f"Molecule resolution failed for '{target_text}'. "
                    "Please provide a valid SMILES and click Continue."
                )
                self.query_one("#btn-continue", Button).disabled = False
                self.app.save_state()
                return
        else:
            # Allow continuing to structure step but must resolve before scoring
            self.app.engine.pause(state, reason="Missing target molecule.")
            self.query_one("#intake-message", Static).update(
                "No target molecule provided. You may continue to structure prediction, "
                "but you must provide a target before scoring."
            )
            self.query_one("#btn-continue", Button).disabled = False
            self.app.save_state()
            return

        # Optional fields
        mod_region = result.get("modification_region")
        if mod_region:
            state.input_payload["modification_region"] = mod_region

        self.app.save_state()
        self._update_for_state()
