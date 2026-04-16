from __future__ import annotations

import itertools
import tempfile

import pytest

from aptgent.adapters import molecule as molecule_module
from aptgent.adapters.predictor import EnsembleAdapter
from aptgent.domain.enums import Status, Step
from aptgent.domain.models import CandidateSequence, TargetMolecule
from aptgent.workflow.engine import WorkflowEngine
from aptgent.workflow.persistence import Persistence


class FakeEnsembleAdapter(EnsembleAdapter):
    def _predict_batch_via_csv(self, candidates, target):
        from aptgent.domain.models import PredictionResult

        smiles = target.smiles or ""
        results = []
        for idx, cand in enumerate(candidates):
            cand_id = cand.candidate_id or f"cand_{idx}"
            individual = {
                "model_a": {"label": 1, "probability": 0.8},
                "model_b": {"label": 1, "probability": 0.6},
                "model_c": {"label": 1, "probability": 0.7},
            }
            probs = [v["probability"] for v in individual.values()]
            avg_prob = sum(probs) / len(probs)
            results.append(
                PredictionResult(
                    candidate_id=cand_id,
                    model_name="ensemble",
                    target=smiles,
                    score=avg_prob,
                    label=1,
                    probability=avg_prob,
                    raw_outputs={"individual": individual},
                )
            )
        return results


def test_create_and_load_run():
    with tempfile.TemporaryDirectory() as tmpdir:
        persistence = Persistence(tmpdir)
        engine = WorkflowEngine(persistence)
        state = engine.create_run("run_1")
        assert state.run_id == "run_1"
        assert state.current_step == Step.INTAKE

        loaded = engine.load_run("run_1")
        assert loaded is not None
        assert loaded.run_id == "run_1"


def test_transition_validation():
    with tempfile.TemporaryDirectory() as tmpdir:
        persistence = Persistence(tmpdir)
        engine = WorkflowEngine(persistence)
        state = engine.create_run("run_2")
        engine.transition_to(state, Step.SECONDARY_STRUCTURE)
        assert state.current_step == Step.SECONDARY_STRUCTURE


def test_intake_self_loop_transition_is_valid():
    with tempfile.TemporaryDirectory() as tmpdir:
        persistence = Persistence(tmpdir)
        engine = WorkflowEngine(persistence)
        state = engine.create_run("run_retry")

        engine.transition_to(state, Step.INTAKE, metadata={"reenter": True})

        assert state.current_step == Step.INTAKE


def test_pause_and_resume():
    with tempfile.TemporaryDirectory() as tmpdir:
        persistence = Persistence(tmpdir)
        engine = WorkflowEngine(persistence)
        state = engine.create_run("run_3")
        engine.pause(state, reason="missing_smiles", pending_input={"field": "smiles"})
        assert state.status == Status.PAUSED
        assert state.pending_input is not None

        engine.resume(state)
        assert state.status == Status.RUNNING
        assert state.pending_input is None


def test_molecule_resolver_smiles_without_rdkit(monkeypatch):
    monkeypatch.setattr(molecule_module, "_check_rdkit", lambda: False)
    resolver = molecule_module.SimpleMoleculeResolver()

    result = resolver.resolve("C1=CC=CC=C1")

    assert result.resolution_status == "resolved"
    assert result.smiles == "C1=CC=CC=C1"


def test_molecule_resolver_rejects_names_without_rdkit(monkeypatch):
    monkeypatch.setattr(molecule_module, "_check_rdkit", lambda: False)
    resolver = molecule_module.SimpleMoleculeResolver()

    # Direct heuristic validation: long alphabetic names and CJK should
    # not be treated as SMILES when RDKit is unavailable.
    assert resolver._validate_smiles("theophylline") is False
    assert resolver._validate_smiles("茶碱") is False

    # If PubChem lookup also fails, the name should resolve to failed.
    monkeypatch.setattr(
        resolver, "_pubchem_name_to_smiles", lambda name: None
    )
    result = resolver.resolve("theophylline")
    assert result.resolution_status == "failed"
    assert result.smiles is None


def test_candidate_enumeration_logic():
    seq = "AAA"
    sites = [1]
    bases = ["T", "G", "C"]

    candidates = []
    for combo in itertools.product(bases, repeat=len(sites)):
        new_seq = list(seq)
        for idx, base in zip(sites, combo):
            new_seq[idx] = base
        candidates.append("".join(new_seq))

    assert len(candidates) == 3
    assert "ATA" in candidates
    assert "AGA" in candidates
    assert "ACA" in candidates


def test_predictor_adapter_batch_uses_ensemble_rule():
    adapter = FakeEnsembleAdapter()
    candidates = [
        CandidateSequence(
            sequence="GGGAGAAUUCCCGCGGCAGAAGCCCACCUGGCUUUGAACUCUAUGUUAUUGGGUGGGGGAAACUUAAGAAAACUACCACCCUUCAACAUUACCGCCCUUCAGCCUGCCAGCGCCCUGCAGCCCGGGAAGCUU",
            candidate_id="c1",
            mutations=[],
        ),
    ]
    target = TargetMolecule(
        input_text="test",
        smiles="C1=CC=CC=C1",
        resolution_status="resolved",
    )

    results = adapter.predict_batch(candidates, target)

    assert len(results) == 1
    assert results[0].candidate_id == "c1"
    assert results[0].label == 1
    assert results[0].probability == pytest.approx(0.7)
