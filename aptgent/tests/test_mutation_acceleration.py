from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

from aptgent.adapters.predictor import EnsembleAdapter
from aptgent.domain.enums import Step
from aptgent.domain.models import CandidateSequence, PredictionResult, TargetMolecule
from aptgent.predictor_runtime import features as runtime_features
from aptgent.predictor_runtime.predictor import EnsemblePredictor
from aptgent.tui.steps.enumeration import EnumerationHandler
from aptgent.workflow.persistence import Persistence


class ThresholdModel:
    def __init__(self, feature_index: int, threshold: float, hit_probability: float) -> None:
        self.feature_index = feature_index
        self.threshold = threshold
        self.hit_probability = hit_probability

    def predict(self, X):
        return (X[:, self.feature_index] >= self.threshold).astype(int)

    def predict_proba(self, X):
        preds = self.predict(X)
        probs = [
            self.hit_probability if pred else 1.0 - self.hit_probability
            for pred in preds
        ]
        return runtime_features.np.column_stack([1.0 - runtime_features.np.array(probs), probs])


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


def test_build_feature_matrix_matches_single_vector_builder(monkeypatch):
    monkeypatch.setattr(
        runtime_features,
        "molecular_descriptors",
        lambda _smiles: [0.25, 0.75],
    )

    sequences = ["AA", "AG", "AT"]
    matrix = runtime_features.build_feature_matrix(sequences, [0.25, 0.75], [1, 2])
    expected = runtime_features.np.vstack(
        [
            runtime_features.build_feature_vector(sequence, "ignored", [1, 2])
            for sequence in sequences
        ]
    )

    assert matrix.shape == expected.shape
    assert runtime_features.np.allclose(matrix, expected)


def test_predict_mutation_batch_filters_to_strict_ensemble_hits(monkeypatch):
    monkeypatch.setattr(
        runtime_features,
        "molecular_descriptors",
        lambda _smiles: [0.1],
    )

    predictor = object.__new__(EnsemblePredictor)
    predictor.models = [
        (ThresholdModel(feature_index=0, threshold=0.5, hit_probability=0.8), "1mer", "model_a"),
        (ThresholdModel(feature_index=2, threshold=0.5, hit_probability=0.9), "1mer", "model_b"),
    ]

    results = predictor.predict_mutation_batch("AA", "C1=CC=CC=C1", [1], batch_size=4)

    assert [item["sequence"] for item in results] == ["AG"]
    assert results[0]["ensemble_label"] == 1
    assert results[0]["mean_probability"] == pytest.approx(0.85)


def test_search_mutation_space_reconstructs_candidates_and_predictions(monkeypatch):
    adapter = EnsembleAdapter(model_dir="/tmp/models")
    payload = {
        "results": [
            {
                "sequence": "AG",
                "mean_probability": 0.85,
                "ensemble_label": 1,
                "individual": {
                    "model_a": {"label": 1, "probability": 0.8},
                    "model_b": {"label": 1, "probability": 0.9},
                },
            }
        ],
        "total_processed": 4,
        "binding_hit_count": 1,
    }

    def fake_run(extra_args, timeout=600):
        assert "mutation-search" in extra_args
        return subprocess.CompletedProcess(
            args=extra_args,
            returncode=0,
            stdout=json.dumps(payload),
            stderr="",
        )

    monkeypatch.setattr(adapter, "_run", fake_run)
    target = TargetMolecule(
        input_text="benzene",
        smiles="C1=CC=CC=C1",
        resolution_status="resolved",
    )

    candidates, predictions, metadata = adapter.search_mutation_space(
        "AA",
        target,
        [1],
        top_k_keep=5,
    )

    assert [candidate.sequence for candidate in candidates] == ["AG"]
    assert candidates[0].mutations[0].position == 1
    assert candidates[0].mutations[0].original == "A"
    assert candidates[0].mutations[0].mutated == "G"
    assert predictions[0].candidate_id == "cand_0"
    assert predictions[0].probability == pytest.approx(0.85)
    assert metadata["total_processed"] == 4
    assert metadata["binding_hit_count"] == 1


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
