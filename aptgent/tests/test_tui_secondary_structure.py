from __future__ import annotations

import pytest

from aptgent.domain.enums import Step
from aptgent.tui.widgets.chat_widgets import SystemBubble

from tui_helpers import CountingRNAFoldAdapter, FakePdbAnalysisAdapter, anyio_backend, make_app


@pytest.mark.anyio
async def test_secondary_structure_hides_not_configured_lookup_note(tmp_path):
    app = make_app(tmp_path)
    state = app.engine.create_run("structure_lookup_noise")
    state.current_step = Step.SECONDARY_STRUCTURE
    state.input_payload["initial_sequence"] = "ACGUACGU"
    app.persistence.save(state)

    async with app.run_test() as pilot:
        await pilot.pause()
        app.set_run_id("structure_lookup_noise")
        app.push_screen("chat")
        await pilot.pause()
        await pilot.pause()
        await pilot.pause()

        bubble_texts = [
            bubble._text
            for bubble in app.screen.query(SystemBubble)
            if hasattr(bubble, "_text")
        ]
        assert not any("No structure lookup adapter is configured" in text for text in bubble_texts)
        assert app.current_state.context.secondary_structure.note == "Secondary structure generated from RNAfold."
@pytest.mark.anyio
async def test_secondary_structure_prefers_pdb_derived_result_when_pdb_context_exists(tmp_path):
    rnafold = CountingRNAFoldAdapter()
    app = make_app(
        tmp_path,
        rna_fold_adapter=rnafold,
        pdb_analysis_adapter=FakePdbAnalysisAdapter(),
    )
    state = app.engine.create_run("structure_from_pdb")
    state.current_step = Step.SECONDARY_STRUCTURE
    state.input_payload["initial_sequence"] = "ACGU"
    state.context.pdb_intake.pdb_id = "1EHZ"
    state.context.pdb_intake.artifact_path = str(tmp_path / "1EHZ.pdb")
    state.context.pdb_intake.selected_chain_id = "A"
    app.persistence.save(state)

    async with app.run_test() as pilot:
        await pilot.pause()
        app.set_run_id("structure_from_pdb")
        app.push_screen("chat")
        await pilot.pause()
        await pilot.pause()
        await pilot.pause()

        assert rnafold.calls == []
        assert app.current_state.secondary_structure is not None
        assert app.current_state.secondary_structure.dot_bracket == "(())"
        assert app.current_state.context.secondary_structure.source == "pdb"
        bubble_texts = [
            bubble._text
            for bubble in app.screen.query(SystemBubble)
            if hasattr(bubble, "_text")
        ]
        assert any("Using PDB-derived secondary structure." in text for text in bubble_texts)
