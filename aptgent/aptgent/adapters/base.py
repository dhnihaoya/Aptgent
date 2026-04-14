from typing import Protocol

from aptgent.domain.models import (
    CandidateSequence,
    PredictionResult,
    SecondaryStructure,
    SpatialRankResult,
    TargetMolecule,
)


class StructureAdapter(Protocol):
    def fold(self, sequence: str) -> SecondaryStructure: ...


class PredictionAdapter(Protocol):
    def predict_batch(
        self,
        candidates: list[CandidateSequence],
        target: TargetMolecule,
    ) -> list[PredictionResult]: ...


class MoleculeAdapter(Protocol):
    def resolve(self, input_text: str) -> TargetMolecule: ...


class SpatialRankAdapter(Protocol):
    def rank_batch(
        self,
        candidates: list[CandidateSequence],
        target: TargetMolecule,
    ) -> list[SpatialRankResult]: ...
