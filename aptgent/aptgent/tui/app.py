from __future__ import annotations

from typing import Any

from textual.app import App
from textual.binding import Binding

from aptgent.bootstrap import (
    build_runtime,
    create_engine,
    create_molecule_resolver,
    create_pdb_analysis_adapter,
    create_persistence,
    create_prediction_adapter,
    create_rna_fold_adapter,
    create_spatial_rank_adapter,
    create_vina_adapter,
    load_config,
)
from aptgent.domain.enums import Step
from aptgent.tui.commands import get_theme_preset
from aptgent.tui.screens.chat import ChatScreen
from aptgent.tui.screens.quit_confirm import QuitConfirmScreen
from aptgent.tui.screens.welcome import WelcomeScreen
from aptgent.tui.widgets import StatusPanel, StepProgressBar
from aptgent.workflow.state import RunState
from aptgent.adapters.structure_services import (
    NoopStructureFetchAdapter,
    NoopStructureLookupAdapter,
    NoopTertiaryStructureAdapter,
)
from aptgent.llm.skills import IntakeSkill, PdbReviewSkill


class AptgentApp(App):
    """Main Textual application for aptamer design workflow."""

    TITLE = "Aptgent"
    SUB_TITLE = "Aptamer Design Assistant"
    CSS_PATH = "styles/main.tcss"
    DEFAULT_THEME = "textual-dark"

    SCREENS = {
        "welcome": WelcomeScreen,
        "chat": ChatScreen,
    }

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", priority=True),
    ]

    def __init__(
        self,
        *,
        config: dict[str, Any] | None = None,
        tools_config: dict[str, Any] | None = None,
        persistence: Any | None = None,
        engine: Any | None = None,
        rna_fold_adapter: Any | None = None,
        vina_adapter: Any | None = None,
        prediction_adapter: Any | None = None,
        molecule_resolver: Any | None = None,
        spatial_rank_adapter: Any | None = None,
        pdb_analysis_adapter: Any | None = None,
        structure_lookup_adapter: Any | None = None,
        structure_fetch_adapter: Any | None = None,
        tertiary_structure_adapter: Any | None = None,
        intake_skill_factory: Any | None = None,
        pdb_review_skill_factory: Any | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        config_bundle = None
        if config is None or tools_config is None:
            config_bundle = load_config()

        self.config = config if config is not None else config_bundle.workflow
        self.tools_config = (
            tools_config if tools_config is not None else config_bundle.tools
        )
        self.llm_config = config_bundle.llm if config_bundle is not None else {}
        self.persistence = (
            persistence if persistence is not None else create_persistence(self.config)
        )
        self.engine = engine if engine is not None else create_engine(self.persistence)

        self.rna_fold_adapter = (
            rna_fold_adapter
            if rna_fold_adapter is not None
            else create_rna_fold_adapter(self.tools_config)
        )
        self.vina_adapter = (
            vina_adapter
            if vina_adapter is not None
            else create_vina_adapter(self.tools_config)
        )
        self.prediction_adapter = (
            prediction_adapter
            if prediction_adapter is not None
            else create_prediction_adapter(self.tools_config)
        )
        self.molecule_resolver = (
            molecule_resolver
            if molecule_resolver is not None
            else create_molecule_resolver()
        )
        self.spatial_rank_adapter = (
            spatial_rank_adapter
            if spatial_rank_adapter is not None
            else create_spatial_rank_adapter()
        )
        self.pdb_analysis_adapter = (
            pdb_analysis_adapter
            if pdb_analysis_adapter is not None
            else create_pdb_analysis_adapter(self.tools_config)
        )
        self.structure_lookup_adapter = (
            structure_lookup_adapter
            if structure_lookup_adapter is not None
            else NoopStructureLookupAdapter()
        )
        self.structure_fetch_adapter = (
            structure_fetch_adapter
            if structure_fetch_adapter is not None
            else NoopStructureFetchAdapter()
        )
        self.tertiary_structure_adapter = (
            tertiary_structure_adapter
            if tertiary_structure_adapter is not None
            else NoopTertiaryStructureAdapter()
        )
        self.intake_skill_factory = (
            intake_skill_factory if intake_skill_factory is not None else IntakeSkill
        )
        self.pdb_review_skill_factory = (
            pdb_review_skill_factory
            if pdb_review_skill_factory is not None
            else PdbReviewSkill
        )

        self._state: RunState | None = None
        self._pending_start_message: str | None = None

        self.progress_bar = StepProgressBar(Step.INTAKE, id="progress-bar")
        self.status_panel = StatusPanel("", "", id="status-panel")
        self.theme = self.DEFAULT_THEME

    @property
    def current_state(self) -> RunState:
        if self._state is None:
            raise RuntimeError("No active run state.")
        return self._state

    def set_run_id(self, run_id: str) -> None:
        self._state = self.engine.load_run(run_id)
        if self._state is None:
            self._state = self.engine.create_run(run_id)
        self._pending_start_message = None
        self.progress_bar.set_step(self._state.current_step)
        self.status_panel.set_status(run_id, self._state.status.value)

    def start_new_run(self, *, initial_message: str | None = None) -> RunState:
        state = self.engine.create_run()
        self._state = state
        self._pending_start_message = initial_message
        self.progress_bar.set_step(state.current_step)
        self.status_panel.set_status(state.run_id, state.status.value)
        return state

    def consume_pending_start_message(self) -> str | None:
        message = self._pending_start_message
        self._pending_start_message = None
        return message

    def save_state(self) -> None:
        if self._state:
            self.persistence.save(self._state)
            self.status_panel.set_status(self._state.run_id, self._state.status.value)

    def create_intake_skill(self):
        return self.intake_skill_factory()

    def create_pdb_review_skill(self):
        return self.pdb_review_skill_factory()

    def on_mount(self) -> None:
        self.push_screen("welcome")

    def action_quit(self) -> None:
        self.open_quit_dialog()

    def open_quit_dialog(self) -> None:
        if isinstance(self.screen, QuitConfirmScreen):
            return
        self.push_screen(QuitConfirmScreen(), self._handle_quit_confirmation)

    def apply_theme(self, theme_name: str) -> str | None:
        preset = get_theme_preset(theme_name)
        if preset is None:
            return None
        self.theme = theme_name
        return preset.label

    def _handle_quit_confirmation(self, should_quit: bool | None) -> None:
        if not should_quit:
            return
        self.save_state()
        self.exit()


def run() -> None:
    runtime = build_runtime()
    app = AptgentApp(
        config=runtime.config,
        tools_config=runtime.tools_config,
        persistence=runtime.persistence,
        engine=runtime.engine,
        rna_fold_adapter=runtime.rna_fold_adapter,
        vina_adapter=runtime.vina_adapter,
        prediction_adapter=runtime.prediction_adapter,
        molecule_resolver=runtime.molecule_resolver,
        spatial_rank_adapter=runtime.spatial_rank_adapter,
        pdb_analysis_adapter=runtime.pdb_analysis_adapter,
    )
    app.run()


if __name__ == "__main__":
    run()
