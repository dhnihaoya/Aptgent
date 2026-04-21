from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from aptgent.bootstrap.config import AppConfigBundle, load_config
from aptgent.workflow.engine import WorkflowEngine
from aptgent.workflow.persistence import Persistence


@dataclass(frozen=True)
class AppRuntime:
    config: dict[str, Any]
    tools_config: dict[str, Any]
    llm_config: dict[str, Any]
    persistence: Persistence
    engine: WorkflowEngine
    rna_fold_adapter: Any
    vina_adapter: Any
    prediction_adapter: Any
    molecule_resolver: Any
    spatial_rank_adapter: Any
    pdb_analysis_adapter: Any
    structure_lookup_adapter: Any = None
    structure_fetch_adapter: Any = None
    tertiary_structure_adapter: Any = None
    intake_skill_factory: Callable[[], Any] | None = None
    pdb_review_skill_factory: Callable[[], Any] | None = None
    extras: dict[str, Any] = field(default_factory=dict)


def create_persistence(config: dict[str, Any]) -> Persistence:
    runs_dir = config.get("paths", {}).get("runs_dir", "./runs")
    return Persistence(runs_dir)


def create_engine(persistence: Persistence) -> WorkflowEngine:
    return WorkflowEngine(persistence)


def create_rna_fold_adapter(tools_config: dict[str, Any]) -> Any:
    from aptgent.adapters.rna_fold import RNAfoldAdapter

    rna_cfg = tools_config.get("rna_fold", {})
    return RNAfoldAdapter(
        executable=rna_cfg.get("command", "RNAfold"),
        extra_args=rna_cfg.get("args"),
        lazy=True,
    )


def create_vina_adapter(tools_config: dict[str, Any]) -> Any:
    from aptgent.adapters.docking import VinaAdapter

    dock_cfg = tools_config.get("docking", {})
    return VinaAdapter(
        executable=dock_cfg.get("command", "vina"),
        exhaustiveness=dock_cfg.get("exhaustiveness", 8),
        num_modes=dock_cfg.get("num_modes", 9),
        energy_range=dock_cfg.get("energy_range", 3.0),
        lazy=True,
    )


def create_prediction_adapter(tools_config: dict[str, Any]) -> Any:
    from aptgent.adapters.predictor import EnsembleAdapter

    pred_cfg = tools_config.get("predictor", {})
    return EnsembleAdapter(
        model_dir=pred_cfg.get("model_dir"),
        conda_env=pred_cfg.get("conda_env"),
        conda_python=pred_cfg.get("conda_python"),
    )


def create_molecule_resolver() -> Any:
    from aptgent.adapters.molecule import SimpleMoleculeResolver

    return SimpleMoleculeResolver()


def create_spatial_rank_adapter() -> Any:
    from aptgent.adapters.spatial_rank import SpatialRankAdapter

    return SpatialRankAdapter()


def create_pdb_analysis_adapter(tools_config: dict[str, Any]) -> Any:
    from aptgent.adapters.pdb_analysis import PdbAnalysisAdapter

    pdb_cfg = tools_config.get("pdb_analysis", {})
    return PdbAnalysisAdapter(
        wget_command=pdb_cfg.get("command", "wget"),
        base_url=pdb_cfg.get("base_url", "https://files.rcsb.org/download"),
    )


def build_runtime(config_bundle: AppConfigBundle | None = None) -> AppRuntime:
    from aptgent.adapters.structure_services import (
        NoopStructureFetchAdapter,
        NoopStructureLookupAdapter,
        NoopTertiaryStructureAdapter,
    )
    from aptgent.llm.skills import IntakeSkill, PdbReviewSkill

    bundle = config_bundle or load_config()
    config = bundle.workflow
    tools_config = bundle.tools

    persistence = create_persistence(config)
    engine = create_engine(persistence)

    return AppRuntime(
        config=config,
        tools_config=tools_config,
        llm_config=bundle.llm,
        persistence=persistence,
        engine=engine,
        rna_fold_adapter=create_rna_fold_adapter(tools_config),
        vina_adapter=create_vina_adapter(tools_config),
        prediction_adapter=create_prediction_adapter(tools_config),
        molecule_resolver=create_molecule_resolver(),
        spatial_rank_adapter=create_spatial_rank_adapter(),
        pdb_analysis_adapter=create_pdb_analysis_adapter(tools_config),
        structure_lookup_adapter=NoopStructureLookupAdapter(),
        structure_fetch_adapter=NoopStructureFetchAdapter(),
        tertiary_structure_adapter=NoopTertiaryStructureAdapter(),
        intake_skill_factory=IntakeSkill,
        pdb_review_skill_factory=PdbReviewSkill,
    )
