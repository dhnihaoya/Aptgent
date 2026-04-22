from __future__ import annotations

from types import SimpleNamespace

from aptgent.tui.steps.enumeration import EnumerationHandler


class FakeProgress:
    def __init__(self) -> None:
        self.updates: list[tuple[int, str]] = []

    def set_progress(self, processed: int, text: str) -> None:
        self.updates.append((processed, text))


class FakeScreen:
    def __init__(self) -> None:
        self.app = SimpleNamespace()
        self.messages: list[str] = []

    def add_system_message(self, text: str, *_args) -> None:
        self.messages.append(text)


def test_enumeration_hit_events_update_progress_without_new_messages():
    screen = FakeScreen()
    handler = EnumerationHandler(screen)
    progress = FakeProgress()

    handler._on_job_event(
        {"type": "progress", "done": 128, "total": 256, "extra": {"binding": 1}},
        progress,
    )
    handler._on_job_event(
        {"type": "hit", "candidate_id": "hit_1", "probability": 0.8},
        progress,
    )
    handler._on_job_event(
        {"type": "hit", "candidate_id": "hit_2", "probability": 0.91},
        progress,
    )

    assert screen.messages == []
    assert progress.updates[-1] == (
        128,
        "Progress: 128/256 | Hits: 2 | Best P: 0.9100",
    )

