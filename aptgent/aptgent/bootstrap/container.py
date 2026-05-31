from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Type

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
    receptor_prep_adapter: Any = None
    structure_lookup_adapter: Any = None
    structure_fetch_adapter: Any = None
    tertiary_structure_adapter: Any = None
    llm_client: Any = None
    intake_skill_factory: Callable[[], Any] | None = None
    pdb_review_skill_factory: Callable[[], Any] | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    def create_skill(self, cls: Type) -> Any:
        """Instantiate a skill class with the shared LLMClient."""
        if self.llm_client is not None:
            return cls(client=self.llm_client)
        return cls()


def create_persistence(config: dict[str, Any]) -> Persistence:
    runs_dir = config.get("paths", {}).get("runs_dir", "./runs")
    return Persistence(runs_dir)


def create_engine(
    persistence: Persistence,
    tools_config: dict[str, Any] | None = None,
    llm_config: dict[str, Any] | None = None,
) -> WorkflowEngine:
    return WorkflowEngine(persistence, tools_config=tools_config, llm_config=llm_config)


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


def _ensure_model_dir(tools_config: dict[str, Any]) -> dict[str, Any]:
    """Populate predictor.model_dir with the bundled default if not set."""
    from aptgent.predictor_runtime.paths import default_model_dir
    pred_cfg = tools_config.setdefault("predictor", {})
    if not pred_cfg.get("model_dir"):
        pred_cfg["model_dir"] = str(default_model_dir())
    return tools_config


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


def create_receptor_prep_adapter(tools_config: dict[str, Any]) -> Any:
    from aptgent.adapters.receptor_prep import ReceptorPreparationAdapter

    cfg = tools_config.get("receptor_prep", {})
    return ReceptorPreparationAdapter(
        obabel_command=cfg.get("obabel", "obabel"),
        default_padding=float(cfg.get("padding_angstrom", 4.0)),
        minimize_steps=int(cfg.get("minimize_steps", 500)),
    )


def create_rnacomposer_adapter(tools_config: dict[str, Any]) -> Any:
    from aptgent.adapters.rnacomposer import RNAComposerAdapter

    cfg = tools_config.get("rnacomposer", {})
    return RNAComposerAdapter(
        base_url=cfg.get("base_url", "https://rnacomposer.cs.put.poznan.pl"),
        timeout_seconds=int(cfg.get("timeout_seconds", 60)),
        max_poll_seconds=int(cfg.get("max_poll_seconds", 1800)),
        poll_interval_seconds=int(cfg.get("poll_interval_seconds", 15)),
    )


def _create_llm_client(llm_config: dict[str, Any]) -> Any:
    from aptgent.llm.client import LLMClient

    provider_cfg = llm_config.get("provider", {}).get("openai", llm_config)
    return LLMClient(config=provider_cfg)


def build_runtime(config_bundle: AppConfigBundle | None = None) -> AppRuntime:
    from aptgent.adapters.structure_services import (
        NoopStructureFetchAdapter,
        NoopStructureLookupAdapter,
    )
    from aptgent.llm.skills import IntakeSkill, PdbReviewSkill

    bundle = config_bundle or load_config()
    config = bundle.workflow
    tools_config = _ensure_model_dir(bundle.tools)

    persistence = create_persistence(config)
    engine = create_engine(persistence, tools_config=tools_config, llm_config=bundle.llm)
    llm_client = _create_llm_client(bundle.llm)

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
        receptor_prep_adapter=create_receptor_prep_adapter(tools_config),
        structure_lookup_adapter=NoopStructureLookupAdapter(),
        structure_fetch_adapter=NoopStructureFetchAdapter(),
        tertiary_structure_adapter=create_rnacomposer_adapter(tools_config),
        llm_client=llm_client,
        intake_skill_factory=lambda: IntakeSkill(client=llm_client),
        pdb_review_skill_factory=lambda: PdbReviewSkill(client=llm_client),
    )
