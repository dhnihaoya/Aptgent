from __future__ import annotations

from types import SimpleNamespace

from aptgent.domain.enums import Step
from aptgent.domain.models import TargetMolecule
from aptgent.tui.steps.enumeration import EnumerationHandler
from aptgent.workflow.persistence import Persistence


class FakeProgress:
    def __init__(self) -> None:
        self.updates: list[tuple[int, str]] = []
        self.finished_message = ""

    def set_progress(self, processed: int, text: str) -> None:
        self.updates.append((processed, text))

    def finish(self, text: str) -> None:
        self.finished_message = text


class RecordingEnumerationHandler(EnumerationHandler):
    def __init__(self, screen) -> None:
        super().__init__(screen)
        self.progress = FakeProgress()
        self.attached: dict | None = None

    def _create_progress_bubble(self, total_space: int) -> FakeProgress:
        assert total_space == 256
        return self.progress

    def attach_or_spawn_job(self, **kwargs) -> None:
        self.attached = kwargs


class FakeScreen:
    def __init__(self, app) -> None:
        self.app = app
        self.messages: list[str] = []
        self.advanced_steps: list[Step] = []
        self.input_enabled = True

    def add_system_message(self, text: str, *_args) -> None:
        self.messages.append(text)

    def set_input_enabled(self, enabled: bool) -> None:
        self.input_enabled = enabled

    def advance_to_step(self, step: Step) -> None:
        self.advanced_steps.append(step)

    def add_structured_widget(self, _widget) -> None:
        return None


def test_enumeration_spawns_detached_mutation_batch_job_for_large_spaces(tmp_path):
    persistence = Persistence(tmp_path / "runs")
    state = persistence.init_run("run_1")
    state.context.intake.sequence = "AAAA"
    state.confirmed_mutation_sites = [0, 1, 2, 3]
    state.target_molecule = TargetMolecule(
        input_text="benzene",
        smiles="C1=CC=CC=C1",
        resolution_status="resolved",
    )

    app = SimpleNamespace(
        current_state=state,
        config={
            "paths": {"runs_dir": str(tmp_path / "runs")},
            "enumeration": {
                "top_k_keep": 5,
                "mutation_batch_timeout_seconds": 0,
            },
        },
        persistence=persistence,
    )
    screen = FakeScreen(app)
    handler = RecordingEnumerationHandler(screen)

    handler.enter()

    assert handler.attached is not None
    assert handler.attached["activity"] == "Enumerating and scoring candidates..."
    assert callable(handler.attached["on_event"])
    assert callable(handler.attached["on_done"])
    assert callable(handler.attached["on_error"])
    assert "Mutation space: 4^4 = 256 candidates" in screen.messages[0]
    assert "Top-K kept: 5" in screen.messages[0]
    assert "Timeout: none" in screen.messages[0]
