from __future__ import annotations

import pytest

from aptgent.domain.enums import Step
from aptgent.domain.models import SecondaryStructure, TargetMolecule
from aptgent.tui.app import AptgentApp


class FakeRNAFoldAdapter:
    def fold(self, sequence: str) -> SecondaryStructure:
        return SecondaryStructure(
            sequence=sequence,
            dot_bracket="." * len(sequence),
            mfe=-1.0,
        )


class FakePredictionAdapter:
    def predict_batch(self, candidates, target):
        return []

    def predict_batch_for_targets(self, candidates, targets):
        return {target.smiles or target.input_text: [] for target in targets}


class FakeVinaAdapter:
    def run_batch(self, **kwargs):
        return []


class FakeResolver:
    def resolve(self, text: str) -> TargetMolecule:
        return TargetMolecule(
            input_text=text,
            resolved_name=text,
            smiles="C1=CC=CC=C1",
            resolution_status="resolved",
        )


class FakeSpatialRankAdapter:
    def rank_batch(self, candidates, target):
        return []


def make_app(tmp_path) -> AptgentApp:
    return AptgentApp(
        config={
            "paths": {"runs_dir": str(tmp_path / "runs")},
            "enumeration": {"max_candidates": 5000},
        },
        tools_config={},
        rna_fold_adapter=FakeRNAFoldAdapter(),
        prediction_adapter=FakePredictionAdapter(),
        vina_adapter=FakeVinaAdapter(),
        molecule_resolver=FakeResolver(),
        spatial_rank_adapter=FakeSpatialRankAdapter(),
    )


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_app_registers_only_main_screens():
    assert set(AptgentApp.SCREENS) == {"welcome", "chat"}


def test_set_run_id_restores_saved_progress(tmp_path):
    app = make_app(tmp_path)
    state = app.engine.create_run("resume_case")
    state.current_step = Step.PRIMARY_SCORING
    app.persistence.save(state)

    app.set_run_id("resume_case")

    assert app.current_state.current_step == Step.PRIMARY_SCORING
    assert app.progress_bar.current_step == Step.PRIMARY_SCORING


@pytest.mark.anyio
async def test_welcome_screen_is_default(tmp_path):
    app = make_app(tmp_path)

    async with app.run_test() as pilot:
        await pilot.pause()
        assert type(app.screen).__name__ == "WelcomeScreen"


@pytest.mark.anyio
async def test_create_new_run_enters_chat_screen(tmp_path):
    app = make_app(tmp_path)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click("#btn-new-run")
        await pilot.pause()

        assert type(app.screen).__name__ == "ChatScreen"
        assert app.current_state.current_step == Step.INTAKE
        assert app.screen._handler.__class__.__name__ == "IntakeHandler"
