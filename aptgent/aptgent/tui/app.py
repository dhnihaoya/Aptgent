from __future__ import annotations

from pathlib import Path
from typing import Any

import tomli
from textual.app import App

from aptgent.domain.enums import Step
from aptgent.workflow.state import RunState
from aptgent.tui.widgets import StatusPanel, StepProgressBar
from aptgent.workflow.engine import WorkflowEngine
from aptgent.workflow.persistence import Persistence

# Load configs
_CONFIG_DIR = Path(__file__).parent.parent / "config"

with open(_CONFIG_DIR / "workflow.toml", "rb") as f:
    CONFIG: dict[str, Any] = tomli.load(f)

with open(_CONFIG_DIR / "tools.toml", "rb") as f:
    TOOLS_CONFIG: dict[str, Any] = tomli.load(f)


class AptgentApp(App):
    """Main Textual application for aptamer design workflow."""

    CSS_PATH = "styles/main.tcss"

    # Supported UI path: welcome -> chat.
    SCREENS = {
        "welcome": __import__(
            "aptgent.tui.screens.welcome", fromlist=["WelcomeScreen"]
        ).WelcomeScreen,
        "chat": __import__(
            "aptgent.tui.screens.chat", fromlist=["ChatScreen"]
        ).ChatScreen,
    }

    def __init__(
        self,
        *,
        config: dict[str, Any] | None = None,
        tools_config: dict[str, Any] | None = None,
        persistence: Persistence | None = None,
        engine: WorkflowEngine | None = None,
        rna_fold_adapter: Any | None = None,
        vina_adapter: Any | None = None,
        prediction_adapter: Any | None = None,
        molecule_resolver: Any | None = None,
        spatial_rank_adapter: Any | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.config = config or CONFIG
        self.tools_config = tools_config or TOOLS_CONFIG

        runs_dir = self.config.get("paths", {}).get("runs_dir", "./runs")
        self.persistence = persistence or Persistence(runs_dir)
        self.engine = engine or WorkflowEngine(self.persistence)

        # Configure adapters from tools.toml
        self.rna_fold_adapter = rna_fold_adapter or self._create_rna_fold_adapter()
        self.vina_adapter = vina_adapter or self._create_vina_adapter()
        self.prediction_adapter = prediction_adapter or self._create_prediction_adapter()
        self.molecule_resolver = molecule_resolver or self._create_molecule_resolver()
        self.spatial_rank_adapter = spatial_rank_adapter or self._create_spatial_rank_adapter()

        self._state: RunState | None = None

        self.progress_bar = StepProgressBar(Step.INTAKE, id="progress-bar")
        self.status_panel = StatusPanel("", "", id="status-panel")

    @property
    def current_state(self) -> RunState:
        if self._state is None:
            raise RuntimeError("No active run state.")
        return self._state

    def set_run_id(self, run_id: str) -> None:
        self._state = self.engine.load_run(run_id)
        if self._state is None:
            self._state = self.engine.create_run(run_id)
        self.progress_bar.set_step(self._state.current_step)
        self.status_panel.set_status(run_id, self._state.status.value)

    def save_state(self) -> None:
        if self._state:
            self.persistence.save(self._state)
            self.status_panel.set_status(self._state.run_id, self._state.status.value)

    def on_mount(self) -> None:
        self.push_screen("welcome")

    def _create_rna_fold_adapter(self) -> Any:
        from aptgent.adapters.rna_fold import RNAfoldAdapter

        rna_cfg = self.tools_config.get("rna_fold", {})
        return RNAfoldAdapter(
            executable=rna_cfg.get("command", "RNAfold"),
            extra_args=rna_cfg.get("args"),
            lazy=True,
        )

    def _create_vina_adapter(self) -> Any:
        from aptgent.adapters.docking import VinaAdapter

        dock_cfg = self.tools_config.get("docking", {})
        return VinaAdapter(
            executable=dock_cfg.get("command", "vina"),
            exhaustiveness=dock_cfg.get("exhaustiveness", 8),
            num_modes=dock_cfg.get("num_modes", 9),
            energy_range=dock_cfg.get("energy_range", 3.0),
            lazy=True,
        )

    def _create_prediction_adapter(self) -> Any:
        from aptgent.adapters.predictor import EnsembleAdapter

        pred_cfg = self.tools_config.get("predictor", {})
        return EnsembleAdapter(
            model_dir=pred_cfg.get("model_dir"),
            conda_env=pred_cfg.get("conda_env"),
            conda_python=pred_cfg.get("conda_python"),
        )

    def _create_molecule_resolver(self) -> Any:
        from aptgent.adapters.molecule import SimpleMoleculeResolver

        return SimpleMoleculeResolver()

    def _create_spatial_rank_adapter(self) -> Any:
        from aptgent.adapters.spatial_rank import SpatialRankAdapter

        return SpatialRankAdapter()


def run() -> None:
    app = AptgentApp()
    app.run()


if __name__ == "__main__":
    run()
