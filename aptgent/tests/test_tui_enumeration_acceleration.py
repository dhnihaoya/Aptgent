from __future__ import annotations

from types import SimpleNamespace

import pytest

from aptgent.domain.enums import Step
from aptgent.domain.models import CandidateSequence, PredictionResult, TargetMolecule
from aptgent.tui.steps.enumeration import EnumerationHandler
from aptgent.workflow.persistence import Persistence


class RecordingPredictionAdapter:
    def __init__(self) -> None:
        self.predict_calls: list[tuple[list[CandidateSequence], TargetMolecule]] = []
        self.search_calls: list[tuple[str, TargetMolecule, list[int], int]] = []

    def predict_batch(self, candidates, target):
        self.predict_calls.append((list(candidates), target))
        return []

    def search_mutation_space(self, base_sequence, target, sites, *, top_k_keep):
        self.search_calls.append((base_sequence, target, list(sites), top_k_keep))
        candidate = CandidateSequence(sequence="GGGG", candidate_id="cand_0")
        prediction = PredictionResult(
            candidate_id="cand_0",
            model_name="ensemble",
            target=target.smiles or "",
            score=0.91,
            label=1,
            probability=0.91,
            raw_outputs={"individual": {"m1": {"label": 1, "probability": 0.91}}},
        )
        return [candidate], [prediction], {"total_processed": 256, "binding_hit_count": 1}
class FakeProgress:
    def __init__(self) -> None:
        self.updates: list[tuple[int, str]] = []
        self.finished_message = ""

    def set_progress(self, processed: int, text: str) -> None:
        self.updates.append((processed, text))

    def finish(self, text: str) -> None:
        self.finished_message = text
class RecordingEnumerationHandler(EnumerationHandler):
    def __init__(self, screen) -> None:
        super().__init__(screen)
        self.progress = FakeProgress()

    def _create_progress_bubble(self, total_space: int) -> FakeProgress:
        assert total_space == 256
        return self.progress
class FakeScreen:
    def __init__(self, app) -> None:
        self.app = app
        self.messages: list[str] = []
        self.advanced_steps: list[Step] = []
        self.activity = ""
        self.input_enabled = True

    def add_system_message(self, text: str, *_args) -> None:
        self.messages.append(text)

    def set_input_enabled(self, enabled: bool) -> None:
        self.input_enabled = enabled

    def show_activity(self, activity: str) -> None:
        self.activity = activity

    def run_worker(self, work, **_kwargs) -> None:
        work()

    def advance_to_step(self, step: Step) -> None:
        self.advanced_steps.append(step)

    def add_structured_widget(self, _widget) -> None:
        return None
def test_enumeration_uses_accelerated_search_for_large_spaces(tmp_path, monkeypatch):
    prediction_adapter = RecordingPredictionAdapter()
    persistence = Persistence(tmp_path / "runs")
    state = persistence.init_run("run_1")
    state.context.intake.sequence = "AAAA"
    state.confirmed_mutation_sites = [0, 1, 2, 3]
    state.target_molecule = TargetMolecule(
        input_text="benzene",
        smiles="C1=CC=CC=C1",
        resolution_status="resolved",
    )

    app = SimpleNamespace(
        current_state=state,
        config={
            "paths": {"runs_dir": str(tmp_path / "runs")},
            "enumeration": {
                "batch_size": 16,
                "top_k_keep": 5,
                "acceleration_threshold": 128,
            },
        },
        prediction_adapter=prediction_adapter,
        persistence=persistence,
        call_from_thread=lambda func, *args, **kwargs: func(*args, **kwargs),
        save_state=lambda: persistence.save(state),
    )
    screen = FakeScreen(app)
    handler = RecordingEnumerationHandler(screen)

    monkeypatch.setattr(
        "textual.worker.get_current_worker",
        lambda: SimpleNamespace(is_cancelled=False),
    )

    handler.enter()

    assert prediction_adapter.search_calls == [
        ("AAAA", state.target_molecule, [0, 1, 2, 3], 5)
    ]
    assert prediction_adapter.predict_calls == []
    assert state.candidates[0].sequence == "GGGG"
    assert state.predictions[0].probability == pytest.approx(0.91)
    assert screen.advanced_steps == [Step.PRIMARY_SCORING]
    assert (tmp_path / "runs" / "run_1" / "artifacts" / "scored_candidates.jsonl").exists()
