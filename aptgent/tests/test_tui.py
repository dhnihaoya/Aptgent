import pytest

from aptgent.tui.app import AptgentApp


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_welcome_to_intake():
    app = AptgentApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert type(app.screen).__name__ == "WelcomeScreen"

        app.set_run_id("tui_test_1")
        app.push_screen("intake")
        await pilot.pause()
        assert type(app.screen).__name__ == "IntakeScreen"


@pytest.mark.anyio
async def test_full_flow_navigation():
    app = AptgentApp()
    async with app.run_test() as pilot:
        await pilot.pause()

        app.set_run_id("tui_test_2")
        app.current_state.input_payload["initial_sequence"] = "GGGAAACCC"
        app.current_state.target_molecule = app.molecule_resolver.resolve("C1=CC=CC=C1")
        app.current_state.confirmed_mutation_sites = [3, 4]

        screen_name_to_class = {
            "intake": "IntakeScreen",
            "secondary_structure": "StructureScreen",
            "site_proposal": "SiteProposalScreen",
            "candidate_enumeration": "EnumerationScreen",
            "primary_scoring": "ScoringScreen",
            "specificity_filter": "SpecificityFilterScreen",
            "docking_selection": "DockingSelectionScreen",
            "docking_run": "DockingRunScreen",
            "spatial_rank": "SpatialRankScreen",
            "final_report": "ReportScreen",
        }
        for screen_name, expected_class in screen_name_to_class.items():
            app.push_screen(screen_name)
            await pilot.pause()
            assert type(app.screen).__name__ == expected_class


@pytest.mark.anyio
async def test_enumeration_exceeds_limit():
    app = AptgentApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.set_run_id("tui_test_3")
        app.current_state.input_payload["initial_sequence"] = "A" * 20
        # 10 sites -> 4^10 = 1,048,576 > 5000 limit
        app.current_state.confirmed_mutation_sites = list(range(10))

        app.push_screen("candidate_enumeration")
        await pilot.pause()
        assert type(app.screen).__name__ == "EnumerationScreen"
        # Screen should show error and keep continue button disabled
        btn = app.screen.query_one("#btn-continue")
        assert btn.disabled is True
