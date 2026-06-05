from __future__ import annotations

from aptgent.tui.steps.docking_run import DockingRunHandler


class FakeScreen:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def add_system_message(self, text: str, *_args, **_kwargs) -> None:
        self.messages.append(text)


def test_docking_run_hit_event_ignores_malformed_extra():
    screen = FakeScreen()
    handler = DockingRunHandler(screen)

    handler._on_job_event(
        {"type": "hit", "candidate_id": "cand_1", "extra": ["not", "a", "dict"]}
    )

    assert screen.messages == ["  cand_1: N/A"]
