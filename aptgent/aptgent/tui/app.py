from __future__ import annotations

from typing import Any

from textual.app import App
from textual.binding import Binding
from textual.theme import Theme

from aptgent.bootstrap import AppRuntime, build_runtime, create_engine, create_persistence
from aptgent.domain.enums import Step
from aptgent.tui.commands import get_theme_preset
from aptgent.tui.rich_theme import build_chat_markdown_theme
from aptgent.tui.screens.chat import ChatScreen
from aptgent.tui.screens.quit_confirm import QuitConfirmScreen
from aptgent.tui.screens.welcome import WelcomeScreen
from aptgent.tui.widgets import StatusPanel, StepProgressBar
from aptgent.workflow.state import RunState

_THEME_VARIABLE_DEFAULTS = {
    "button-color-foreground": "#071018",
    "input-selection-background": "#5D95D633",
    "chat-system-background": "#121922",
    "chat-system-foreground": "#DFE7F0",
    "chat-system-accent": "#5D95D6",
    "chat-stream-background": "#18212C",
    "chat-stream-foreground": "#E6EDF7",
    "chat-stream-accent": "#78B7F2",
    "chat-tool-background": "#10161E",
    "chat-tool-foreground": "#AFBDCD",
    "chat-tool-accent": "#4F667F",
    "chat-user-background": "#102238",
    "chat-user-foreground": "#EEF4FB",
    "chat-user-accent": "#78B7F2",
    "chat-thinking-background": "#10161E",
    "chat-thinking-foreground": "#AEBBCB",
    "chat-thinking-accent": "#D3A751",
    "chat-thinking-frame-muted": "#718198",
    "chat-thinking-frame-soft": "#9BAABD",
    "chat-thinking-frame-bright": "#D7E2EE",
    "chat-thinking-frame-hot": "#F1C15B",
    "chat-activity-background": "#111821",
    "chat-activity-foreground": "#D5DEE9",
    "chat-activity-accent": "#F1C15B",
    "chat-activity-label": "#A9BAD1",
    "chat-activity-frame-muted": "#5F6B7A",
    "chat-activity-frame-soft": "#8795A7",
    "chat-activity-frame-bright": "#D7DEEA",
    "chat-activity-frame-hot": "#F1C15B",
    "chat-activity-final-icon": "#F1C15B",
    "chat-progress-background": "#0D131B",
    "chat-progress-foreground": "#9AACBF",
    "chat-progress-border": "#254A72",
    "chat-status-background": "#10161D",
    "chat-status-foreground": "#8B9EB0",
    "chat-status-border": "#1A314A",
    "chat-divider-color": "#84BCF3",
    "chat-markdown-code": "#8EC5FF",
}


def _build_theme(
    *,
    name: str,
    primary: str,
    secondary: str,
    warning: str,
    error: str,
    success: str,
    accent: str,
    foreground: str,
    background: str,
    surface: str,
    panel: str,
    dark: bool,
    variables: dict[str, str],
) -> Theme:
    return Theme(
        name=name,
        primary=primary,
        secondary=secondary,
        warning=warning,
        error=error,
        success=success,
        accent=accent,
        foreground=foreground,
        background=background,
        surface=surface,
        panel=panel,
        dark=dark,
        variables={**_THEME_VARIABLE_DEFAULTS, **variables},
    )


CLEAR_LANES_THEME = _build_theme(
    name="clear-lanes",
    primary="#5D95D6",
    secondary="#274A73",
    warning="#F1C15B",
    error="#C97C8B",
    success="#6DB28C",
    accent="#78B7F2",
    foreground="#DFE7F0",
    background="#060A0F",
    surface="#0D131A",
    panel="#121A23",
    dark=True,
    variables={},
)

CLEAN_MINIMAL_LIGHT_THEME = _build_theme(
    name="clean-minimal-light",
    primary="#376FA8",
    secondary="#D7E4F0",
    warning="#C58A1F",
    error="#B55F6B",
    success="#4C8A65",
    accent="#5F90C3",
    foreground="#1D2732",
    background="#F5F7FA",
    surface="#E9EEF3",
    panel="#FFFFFF",
    dark=False,
    variables={
        "button-color-foreground": "#FFFFFF",
        "input-selection-background": "#5F90C333",
        "chat-system-background": "#FFFFFF",
        "chat-system-foreground": "#1E2935",
        "chat-system-accent": "#3F78AF",
        "chat-stream-background": "#F4F8FC",
        "chat-stream-foreground": "#24303C",
        "chat-stream-accent": "#5F90C3",
        "chat-tool-background": "#EDF2F6",
        "chat-tool-foreground": "#4A5A6B",
        "chat-tool-accent": "#7A8FA3",
        "chat-user-background": "#EAF2FA",
        "chat-user-foreground": "#203040",
        "chat-user-accent": "#5F90C3",
        "chat-thinking-background": "#EFF3F7",
        "chat-thinking-foreground": "#536475",
        "chat-thinking-accent": "#C58A1F",
        "chat-thinking-frame-muted": "#8A98A7",
        "chat-thinking-frame-soft": "#AAB6C2",
        "chat-thinking-frame-bright": "#D6DEE7",
        "chat-thinking-frame-hot": "#C58A1F",
        "chat-activity-background": "#F4ECDD",
        "chat-activity-foreground": "#5A4721",
        "chat-activity-accent": "#C58A1F",
        "chat-activity-label": "#8C7232",
        "chat-activity-frame-muted": "#B3A07A",
        "chat-activity-frame-soft": "#D0C09B",
        "chat-activity-frame-bright": "#E8DBBA",
        "chat-activity-frame-hot": "#C58A1F",
        "chat-activity-final-icon": "#C58A1F",
        "chat-progress-background": "#E8EEF4",
        "chat-progress-foreground": "#486276",
        "chat-progress-border": "#B4C7D8",
        "chat-status-background": "#F0F4F8",
        "chat-status-foreground": "#5C6E80",
        "chat-status-border": "#C8D6E3",
        "chat-divider-color": "#3F78AF",
        "chat-markdown-code": "#376FA8",
    },
)

WARM_INDUSTRIAL_THEME = _build_theme(
    name="warm-industrial",
    primary="#C68A3A",
    secondary="#4A3A2D",
    warning="#E0B56A",
    error="#B97567",
    success="#688E74",
    accent="#5EA5A3",
    foreground="#E7DDD0",
    background="#120E0B",
    surface="#1C1511",
    panel="#261C17",
    dark=True,
    variables={
        "button-color-foreground": "#1B140F",
        "input-selection-background": "#C68A3A33",
        "chat-system-background": "#211914",
        "chat-system-foreground": "#E8DDD0",
        "chat-system-accent": "#C68A3A",
        "chat-stream-background": "#241D17",
        "chat-stream-foreground": "#F0E6DB",
        "chat-stream-accent": "#5EA5A3",
        "chat-tool-background": "#171411",
        "chat-tool-foreground": "#B9C5BF",
        "chat-tool-accent": "#5EA5A3",
        "chat-user-background": "#3A261B",
        "chat-user-foreground": "#F7EEE3",
        "chat-user-accent": "#E0B56A",
        "chat-thinking-background": "#191410",
        "chat-thinking-foreground": "#C5B8AA",
        "chat-thinking-accent": "#D2A15B",
        "chat-thinking-frame-muted": "#7F7064",
        "chat-thinking-frame-soft": "#A89584",
        "chat-thinking-frame-bright": "#D7C9B7",
        "chat-thinking-frame-hot": "#E0B56A",
        "chat-activity-background": "#2B2018",
        "chat-activity-foreground": "#F0E1CD",
        "chat-activity-accent": "#E0B56A",
        "chat-activity-label": "#D8C0A2",
        "chat-activity-frame-muted": "#8D775E",
        "chat-activity-frame-soft": "#B39A7B",
        "chat-activity-frame-bright": "#E0CEB5",
        "chat-activity-frame-hot": "#E0B56A",
        "chat-activity-final-icon": "#E0B56A",
        "chat-progress-background": "#1B1511",
        "chat-progress-foreground": "#BCA898",
        "chat-progress-border": "#4A3A2D",
        "chat-status-background": "#221913",
        "chat-status-foreground": "#AD9988",
        "chat-status-border": "#3B2C23",
        "chat-divider-color": "#D2A15B",
        "chat-markdown-code": "#5EA5A3",
    },
)


class AptgentApp(App):
    """Main Textual application for aptamer design workflow."""

    TITLE = "Aptgent"
    SUB_TITLE = "Aptamer Design Assistant"
    CSS_PATH = "styles/main.tcss"
    DEFAULT_THEME = "clear-lanes"

    SCREENS = {
        "welcome": WelcomeScreen,
        "chat": ChatScreen,
    }

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", priority=True),
    ]

    def __init__(
        self,
        runtime: AppRuntime | None = None,
        **kwargs,
    ) -> None:
        if runtime is None and "config" in kwargs:
            runtime = self._runtime_from_kwargs(kwargs)
        super().__init__(**kwargs)
        if runtime is None:
            runtime = build_runtime()
        self.runtime = runtime

        self.config = runtime.config
        self.tools_config = runtime.tools_config
        self.llm_config = runtime.llm_config
        self.persistence = runtime.persistence
        self.engine = runtime.engine
        self.rna_fold_adapter = runtime.rna_fold_adapter
        self.vina_adapter = runtime.vina_adapter
        self.prediction_adapter = runtime.prediction_adapter
        self.molecule_resolver = runtime.molecule_resolver
        self.spatial_rank_adapter = runtime.spatial_rank_adapter
        self.pdb_analysis_adapter = runtime.pdb_analysis_adapter
        self.receptor_prep_adapter = runtime.receptor_prep_adapter
        self.structure_lookup_adapter = runtime.structure_lookup_adapter
        self.structure_fetch_adapter = runtime.structure_fetch_adapter
        self.tertiary_structure_adapter = runtime.tertiary_structure_adapter
        self.intake_skill_factory = runtime.intake_skill_factory
        self.pdb_review_skill_factory = runtime.pdb_review_skill_factory

        self._state: RunState | None = None
        self._pending_start_message: str | None = None
        self._chat_markdown_theme_pushed = False

        self.progress_bar = StepProgressBar(Step.INTAKE, id="progress-bar")
        self.status_panel = StatusPanel("", "", id="status-panel")
        self.register_theme(CLEAR_LANES_THEME)
        self.register_theme(CLEAN_MINIMAL_LIGHT_THEME)
        self.register_theme(WARM_INDUSTRIAL_THEME)
        self.theme = self.DEFAULT_THEME

    @staticmethod
    def _runtime_from_kwargs(kwargs: dict[str, Any]) -> AppRuntime:
        config = kwargs.pop("config")
        tools_config = kwargs.pop("tools_config", {})
        llm_config = kwargs.pop("llm_config", {})
        persistence = kwargs.pop("persistence", None) or create_persistence(config)
        engine = kwargs.pop("engine", None) or create_engine(
            persistence,
            tools_config=tools_config,
            llm_config=llm_config,
        )
        return AppRuntime(
            config=config,
            tools_config=tools_config,
            llm_config=llm_config,
            persistence=persistence,
            engine=engine,
            rna_fold_adapter=kwargs.pop("rna_fold_adapter", None),
            vina_adapter=kwargs.pop("vina_adapter", None),
            prediction_adapter=kwargs.pop("prediction_adapter", None),
            molecule_resolver=kwargs.pop("molecule_resolver", None),
            spatial_rank_adapter=kwargs.pop("spatial_rank_adapter", None),
            pdb_analysis_adapter=kwargs.pop("pdb_analysis_adapter", None),
            receptor_prep_adapter=kwargs.pop("receptor_prep_adapter", None),
            structure_lookup_adapter=kwargs.pop("structure_lookup_adapter", None),
            structure_fetch_adapter=kwargs.pop("structure_fetch_adapter", None),
            tertiary_structure_adapter=kwargs.pop("tertiary_structure_adapter", None),
            intake_skill_factory=kwargs.pop("intake_skill_factory", None),
            pdb_review_skill_factory=kwargs.pop("pdb_review_skill_factory", None),
        )

    def get_theme_variable_defaults(self) -> dict[str, str]:
        return dict(_THEME_VARIABLE_DEFAULTS)

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

    def reload_current_state(self, run_id: str) -> None:
        """Reload state from persistence and refresh UI widgets."""
        self._state = self.engine.load_run(run_id)
        if self._state is not None:
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
        skill = self.intake_skill_factory()
        self._configure_llm_logging(skill)
        return skill

    def create_pdb_review_skill(self):
        skill = self.pdb_review_skill_factory()
        self._configure_llm_logging(skill)
        return skill

    def _configure_llm_logging(self, skill: Any) -> None:
        if self._state is not None:
            log_dir = self.persistence.run_dir(self._state.run_id) / "logs"
            skill.client.set_log_dir(log_dir)

    def _sync_chat_markdown_theme(self) -> None:
        code_color = self.current_theme.variables.get(
            "chat-markdown-code",
            _THEME_VARIABLE_DEFAULTS["chat-markdown-code"],
        )
        chat_markdown_theme = build_chat_markdown_theme(code_color)
        if self._chat_markdown_theme_pushed:
            self.console.pop_theme()
            self._chat_markdown_theme_pushed = False
        self.console.push_theme(chat_markdown_theme)
        self._chat_markdown_theme_pushed = True

    def on_mount(self) -> None:
        self._sync_chat_markdown_theme()
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
        self._sync_chat_markdown_theme()
        return preset.label

    def _handle_quit_confirmation(self, should_quit: bool | None) -> None:
        if not should_quit:
            return
        self.save_state()
        self.exit(message="Aptgent exited.")


def run() -> None:
    import sys

    if len(sys.argv) >= 2:
        subcmd = sys.argv[1]
        if subcmd == "doctor":
            from aptgent.cli.doctor import run_doctor

            raise SystemExit(run_doctor())
        if subcmd == "run-job":
            from aptgent.jobs.runner import main

            raise SystemExit(main())
    app = AptgentApp(runtime=build_runtime())
    app.run()


if __name__ == "__main__":
    run()
