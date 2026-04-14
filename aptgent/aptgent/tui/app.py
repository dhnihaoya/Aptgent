from __future__ import annotations

from pathlib import Path
from typing import Any

import tomli
from textual.app import App

from aptgent.adapters.docking import VinaAdapter
from aptgent.adapters.molecule import SimpleMoleculeResolver
from aptgent.adapters.predictor import EnsembleAdapter
from aptgent.adapters.rna_fold import RNAfoldAdapter
from aptgent.adapters.spatial_rank import SpatialRankAdapter
from aptgent.domain.enums import Status, Step
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

    SCREENS = {
        "welcome": __import__(
            "aptgent.tui.screens.welcome", fromlist=["WelcomeScreen"]
        ).WelcomeScreen,
        "chat": __import__(
            "aptgent.tui.screens.chat", fromlist=["ChatScreen"]
        ).ChatScreen,
    }

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        runs_dir = CONFIG.get("paths", {}).get("runs_dir", "./runs")
        self.persistence = Persistence(runs_dir)
        self.engine = WorkflowEngine(self.persistence)

        # Configure adapters from tools.toml
        rna_cfg = TOOLS_CONFIG.get("rna_fold", {})
        dock_cfg = TOOLS_CONFIG.get("docking", {})
        pred_cfg = TOOLS_CONFIG.get("predictor", {})

        self.rna_fold_adapter = RNAfoldAdapter(
            executable=rna_cfg.get("command", "RNAfold"),
            extra_args=rna_cfg.get("args"),
            lazy=True,
        )
        self.vina_adapter = VinaAdapter(
            executable=dock_cfg.get("command", "vina"),
            exhaustiveness=dock_cfg.get("exhaustiveness", 8),
            num_modes=dock_cfg.get("num_modes", 9),
            energy_range=dock_cfg.get("energy_range", 3.0),
            lazy=True,
        )
        self.prediction_adapter = EnsembleAdapter(
            model_dir=pred_cfg.get("model_dir"),
            conda_env=pred_cfg.get("conda_env"),
            conda_python=pred_cfg.get("conda_python"),
        )
        self.molecule_resolver = SimpleMoleculeResolver()
        self.spatial_rank_adapter = SpatialRankAdapter()
        self.config = CONFIG

        self._run_id: str | None = None
        self._state: RunState | None = None

        self.progress_bar = StepProgressBar(Step.INTAKE, id="progress-bar")
        self.status_panel = StatusPanel("", "", id="status-panel")

    @property
    def current_state(self) -> RunState:
        if self._state is None:
            raise RuntimeError("No active run state.")
        return self._state

    def set_run_id(self, run_id: str) -> None:
        self._run_id = run_id
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


def run() -> None:
    app = AptgentApp()
    app.run()


if __name__ == "__main__":
    run()
