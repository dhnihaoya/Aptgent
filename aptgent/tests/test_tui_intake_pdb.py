from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from aptgent.domain.enums import Step
from aptgent.domain.models import PdbChainCandidate, PdbLigandCandidate
from aptgent.tui.steps.intake_heuristics import looks_like_full_intake
from aptgent.tui.widgets.structured_input import PdbSelectionPanel
from textual.widgets import Input

from tui_helpers import FakePdbAnalysisAdapter, anyio_backend, make_app


@pytest.mark.anyio
async def test_intake_retry_prompt_sets_retry_placeholder(tmp_path):
    app = make_app(tmp_path)
    state = app.engine.create_run("retry_prompt_case")
    state.input_payload["initial_sequence"] = "ACGU"
    state.context.intake.sequence = "ACGU"
    state.context.intake.phase = "awaiting_target_retry"
    state.context.intake.target_input = "bad target"
    state.context.intake.last_resolution_error = "Lookup failed."
    app.persistence.save(state)

    async with app.run_test() as pilot:
        await pilot.pause()
        app.set_run_id("retry_prompt_case")
        app.push_screen("chat")
        await pilot.pause()

        chat_input = app.screen.query_one("#chat-input", Input)
        bubbles = list(app.screen.query("#chat-log SystemBubble"))

        assert chat_input.placeholder == (
            "Enter a corrected molecule name or SMILES, or paste a full intake brief."
        )
        assert any("**Step 1: Intake Retry**" in bubble._text for bubble in bubbles)
@pytest.mark.anyio
async def test_intake_retry_accepts_full_brief_and_reruns_extraction(tmp_path):
    app = make_app(tmp_path)
    state = app.engine.create_run("retry_full_brief_case")
    state.input_payload["initial_sequence"] = "ACGU"
    state.context.intake.sequence = "ACGU"
    state.context.intake.phase = "awaiting_target_retry"
    state.context.intake.target_input = "bad target"
    state.context.intake.last_resolution_error = "Lookup failed."
    app.persistence.save(state)

    async with app.run_test() as pilot:
        await pilot.pause()
        app.set_run_id("retry_full_brief_case")
        app.push_screen("chat")
        await pilot.pause()

        handler = app.screen._handler
        called = {"extract": False}

        def fake_extract():
            called["extract"] = True

        handler._extract = fake_extract  # type: ignore[attr-defined]
        handler.run_worker = lambda work, activity: work()  # type: ignore[method-assign]

        handler.handle_user_input(
            "Design an aptamer for caffeine with sequence ACGU and low-cost screening."
        )

        assert called["extract"] is True
        assert app.current_state.context.intake.phase == "initial"
        assert app.current_state.input_payload["user_text"].startswith("Design an aptamer")
@pytest.mark.anyio
async def test_intake_retry_full_brief_heuristic_is_conservative_for_pdb_retry(tmp_path):
    app = make_app(tmp_path)
    state = app.engine.create_run("retry_heuristic_case")
    state.context.intake.phase = "awaiting_missing_target"
    state.context.intake.sequence = "ACGU"
    app.persistence.save(state)

    async with app.run_test() as pilot:
        await pilot.pause()
        app.set_run_id("retry_heuristic_case")
        app.push_screen("chat")
        await pilot.pause()

        assert looks_like_full_intake("try pdb 1abc") is False
        assert looks_like_full_intake("sequence ACGU target caffeine") is True
@pytest.mark.anyio
async def test_pdb_input_keeps_sequence_and_requests_missing_target(tmp_path):
    class FakeIntakeSkill:
        client = SimpleNamespace(set_log_dir=lambda *_: None)

        def extract(self, user_text):
            return {
                "pdb_id": "1EHZ",
                "input_mode": "pdb",
                "initial_sequence": None,
                "target_molecule": None,
            }

    class FakePdbReviewSkill:
        client = SimpleNamespace(set_log_dir=lambda *_: None)

        def review(self, payload):
            return {"semantic_status": "aptamer_like", "note": "Looks like a nucleic-acid binder."}

    adapter = FakePdbAnalysisAdapter()
    adapter.result = adapter.result.model_copy(update={"ligands": []})
    app = make_app(
        tmp_path,
        pdb_analysis_adapter=adapter,
        intake_skill_factory=FakeIntakeSkill,
        pdb_review_skill_factory=FakePdbReviewSkill,
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        chat_input = app.screen.query_one("#chat-input", Input)
        chat_input.value = "1ehz"
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        await pilot.pause()

        assert app.current_state.current_step == Step.INTAKE
        assert app.current_state.context.intake.phase == "awaiting_missing_target"
        assert app.current_state.context.intake.sequence == "ACGU"
        assert app.current_state.context.pdb_intake.selected_chain_id == "A"
@pytest.mark.anyio
async def test_pdb_input_with_multiple_candidates_opens_selection_panel(tmp_path):
    class FakeIntakeSkill:
        client = SimpleNamespace(set_log_dir=lambda *_: None)

        def extract(self, user_text):
            return {
                "pdb_id": "1EHZ",
                "input_mode": "pdb",
                "initial_sequence": None,
                "target_molecule": None,
            }

    class FakePdbReviewSkill:
        client = SimpleNamespace(set_log_dir=lambda *_: None)

        def review(self, payload):
            return {"semantic_status": "uncertain", "note": "Needs manual review."}

    adapter = FakePdbAnalysisAdapter()
    adapter.result = adapter.result.model_copy(
        update={
            "nucleic_acid_chains": [
                PdbChainCandidate(chain_id="A", sequence="ACGU", residue_count=4, molecule_type="rna"),
                PdbChainCandidate(chain_id="B", sequence="UGCA", residue_count=4, molecule_type="rna"),
            ],
            "ligands": [
                PdbLigandCandidate(
                    key="X:THP:101",
                    identifier="THP",
                    display_name="theophylline",
                    chain_id="X",
                    residue_number=101,
                    atom_count=12,
                ),
                PdbLigandCandidate(
                    key="Y:CAF:102",
                    identifier="CAF",
                    display_name="caffeine",
                    chain_id="Y",
                    residue_number=102,
                    atom_count=13,
                ),
            ],
        }
    )
    app = make_app(
        tmp_path,
        pdb_analysis_adapter=adapter,
        intake_skill_factory=FakeIntakeSkill,
        pdb_review_skill_factory=FakePdbReviewSkill,
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        chat_input = app.screen.query_one("#chat-input", Input)
        chat_input.value = "pdb 1ehz"
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        await pilot.pause()

        assert app.current_state.context.intake.phase == "awaiting_pdb_selection"
        assert app.screen.query_one(PdbSelectionPanel) is not None
@pytest.mark.anyio
async def test_mixed_pdb_input_prefers_pdb_sequence_over_user_sequence(tmp_path):
    class FakeIntakeSkill:
        client = SimpleNamespace(set_log_dir=lambda *_: None)

        def extract(self, user_text):
            return {
                "pdb_id": "1EHZ",
                "input_mode": "mixed",
                "initial_sequence": "AAAA",
                "target_molecule": "caffeine",
                "mixed_input_detected": True,
            }

    class FakePdbReviewSkill:
        client = SimpleNamespace(set_log_dir=lambda *_: None)

        def review(self, payload):
            return {"semantic_status": "aptamer_like", "note": "PDB import looks usable."}

    app = make_app(
        tmp_path,
        pdb_analysis_adapter=FakePdbAnalysisAdapter(),
        intake_skill_factory=FakeIntakeSkill,
        pdb_review_skill_factory=FakePdbReviewSkill,
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        chat_input = app.screen.query_one("#chat-input", Input)
        chat_input.value = "sequence AAAA, pdb 1ehz, target caffeine"
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        await pilot.pause()

        assert app.current_state.current_step in {
            Step.SECONDARY_STRUCTURE,
            Step.SITE_PROPOSAL,
        }
        assert app.current_state.context.intake.sequence == "ACGU"
        assert app.current_state.context.pdb_intake.sequence_match_status == "mismatch"
def test_pdb_selection_panel_ignores_confirm_when_no_chain_options():
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    panel = PdbSelectionPanel(chain_choices=[], ligand_choices=[])
    fake_menu = SimpleNamespace(option_count=0, highlighted=None)
    posted = []

    panel.query_one = lambda *_args, **_kwargs: fake_menu  # type: ignore[method-assign]
    panel.post_message = lambda message: posted.append(message)  # type: ignore[method-assign]

    panel.on_button_pressed(SimpleNamespace(button=SimpleNamespace(id="btn-confirm-pdb-selection")))

    assert posted == []
