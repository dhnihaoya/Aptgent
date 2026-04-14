import tempfile

from aptgent.adapters.molecule import SimpleMoleculeResolver
from aptgent.adapters.predictor import EnsembleAdapter
from aptgent.domain.enums import Status, Step
from aptgent.domain.models import CandidateSequence, TargetMolecule
from aptgent.workflow.engine import WorkflowEngine
from aptgent.workflow.persistence import Persistence


def test_create_and_load_run():
    with tempfile.TemporaryDirectory() as tmpdir:
        p = Persistence(tmpdir)
        e = WorkflowEngine(p)
        state = e.create_run("run_1")
        assert state.run_id == "run_1"
        assert state.current_step == Step.INTAKE

        loaded = e.load_run("run_1")
        assert loaded is not None
        assert loaded.run_id == "run_1"


def test_transition_validation():
    with tempfile.TemporaryDirectory() as tmpdir:
        p = Persistence(tmpdir)
        e = WorkflowEngine(p)
        state = e.create_run("run_2")
        e.transition_to(state, Step.SECONDARY_STRUCTURE)
        assert state.current_step == Step.SECONDARY_STRUCTURE


def test_pause_and_resume():
    with tempfile.TemporaryDirectory() as tmpdir:
        p = Persistence(tmpdir)
        e = WorkflowEngine(p)
        state = e.create_run("run_3")
        e.pause(state, reason="missing_smiles", pending_input={"field": "smiles"})
        assert state.status == Status.PAUSED
        assert state.pending_input is not None

        e.resume(state)
        assert state.status == Status.RUNNING
        assert state.pending_input is None


def test_molecule_resolver_smiles():
    resolver = SimpleMoleculeResolver()
    result = resolver.resolve("C1=CC=CC=C1")  # benzene SMILES
    assert result.resolution_status == "resolved"
    assert result.smiles == "C1=CC=CC=C1"


def test_candidate_enumeration_logic():
    seq = "AAA"
    sites = [1]
    bases = ["T", "G", "C"]
    import itertools

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


def test_predictor_adapter_batch():
    adapter = EnsembleAdapter()
    cands = [
        CandidateSequence(
            sequence="GGGAGAAUUCCCGCGGCAGAAGCCCACCUGGCUUUGAACUCUAUGUUAUUGGGUGGGGGAAACUUAAGAAAACUACCACCCUUCAACAUUACCGCCCUUCAGCCUGCCAGCGCCCUGCAGCCCGGGAAGCUU",
            candidate_id="c1",
            mutations=[],
        ),
    ]
    target = TargetMolecule(
        input_text="test",
        smiles="C1=CC=C2C(=C1)C(=O)C3=C(C2=O)C(=C(C=C3NC4=CC(=C(C=C4)S(=O)(=O)O)NC5=NC(=NC(=N5)Cl)Cl)S(=O)(=O)O)N",
        resolution_status="resolved",
    )
    results = adapter.predict_batch(cands, target)
    ensemble = [r for r in results if r.model_name == "ensemble"]
    assert len(ensemble) == 1
    assert ensemble[0].candidate_id == "c1"
