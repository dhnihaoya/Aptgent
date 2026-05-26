from __future__ import annotations

import asyncio

import pytest

from aptgent.domain.models import (
    PdbAnalysisResult,
    PdbChainCandidate,
    PdbLigandCandidate,
    SecondaryStructure,
    TargetMolecule,
)
from aptgent.tui.app import AptgentApp


class FakeRNAFoldAdapter:
    def fold(self, sequence: str) -> SecondaryStructure:
        return SecondaryStructure(
            sequence=sequence,
            dot_bracket="." * len(sequence),
            mfe=-1.0,
        )

class CountingRNAFoldAdapter(FakeRNAFoldAdapter):
    def __init__(self) -> None:
        self.calls: list[str] = []

    def fold(self, sequence: str) -> SecondaryStructure:
        self.calls.append(sequence)
        return super().fold(sequence)

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

class FakePdbAnalysisAdapter:
    def __init__(self):
        self.result = PdbAnalysisResult(
            pdb_id="1EHZ",
            title="Example aptamer structure",
            artifact_path="/tmp/1EHZ.pdb",
            nucleic_acid_chains=[
                PdbChainCandidate(chain_id="A", sequence="ACGU", residue_count=4, molecule_type="rna")
            ],
            ligands=[
                PdbLigandCandidate(
                    key="B:THP:101",
                    identifier="THP",
                    display_name="theophylline",
                    chain_id="B",
                    residue_number=101,
                    atom_count=12,
                )
            ],
        )

    def fetch(self, pdb_id, output_dir):
        return output_dir / f"{pdb_id}.pdb"

    def analyze(self, pdb_id, artifact_path):
        return self.result.model_copy(update={"pdb_id": pdb_id, "artifact_path": str(artifact_path)})

    def compare_sequence(self, user_sequence, pdb_sequence):
        if not user_sequence or not pdb_sequence:
            return "unknown"
        return "match" if user_sequence == pdb_sequence else "mismatch"

    def derive_secondary_structure(self, *, pdb_id, artifact_path, chain_id):
        return SecondaryStructure(
            sequence="ACGU",
            dot_bracket="(())",
            mfe=0.0,
            features={
                "source": "pdb_derived",
                "pdb_id": pdb_id,
                "chain_id": chain_id,
                "artifact_path": str(artifact_path),
            },
        )

def make_app(
    tmp_path,
    *,
    rna_fold_adapter=None,
    pdb_analysis_adapter=None,
    intake_skill_factory=None,
    pdb_review_skill_factory=None,
) -> AptgentApp:
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
    return AptgentApp(
        config={
            "paths": {"runs_dir": str(tmp_path / "runs")},
            "enumeration": {"top_k_keep": 500},
        },
        tools_config={},
        rna_fold_adapter=rna_fold_adapter or FakeRNAFoldAdapter(),
        prediction_adapter=FakePredictionAdapter(),
        vina_adapter=FakeVinaAdapter(),
        molecule_resolver=FakeResolver(),
        spatial_rank_adapter=FakeSpatialRankAdapter(),
        pdb_analysis_adapter=pdb_analysis_adapter or FakePdbAnalysisAdapter(),
        intake_skill_factory=intake_skill_factory,
        pdb_review_skill_factory=pdb_review_skill_factory,
    )

@pytest.fixture
def anyio_backend():
    return "asyncio"
