from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, TypedDict


class JobEvent(TypedDict, total=False):
    type: str
    done: int
    total: int
    candidate_id: str
    probability: float
    extra: dict[str, object]


class JobDoneSummary(TypedDict, total=False):
    cancelled: bool
    total: int
    hits: int
    kept: int
    removed: int
    candidates: int
    results_path: str


@dataclass
class JobProgressTracker:
    """Small state holder for TUI progress text derived from job events."""

    done: int = 0
    total: int = 0
    counters: dict[str, int] = field(default_factory=dict)
    best_probability: float | None = None
    current_target: str = ""

    def reset(self, *, total: int = 0) -> None:
        self.done = 0
        self.total = total
        self.counters.clear()
        self.best_probability = None
        self.current_target = ""

    def apply_progress(
        self,
        event: Mapping[str, object],
        *,
        counter_fields: tuple[str, ...] = (),
    ) -> None:
        self.done = _coerce_int(event.get("done"), self.done)
        self.total = _coerce_int(event.get("total"), self.total)
        extra = _event_extra(event)
        for field_name in counter_fields:
            value = _coerce_counter(extra.get(field_name))
            if value is not None:
                self.counters[field_name] = max(
                    self.counter(field_name),
                    value,
                )
        target = extra.get("current_target")
        if isinstance(target, str) and target:
            self.current_target = target

    def apply_probability_hit(self, event: Mapping[str, object]) -> None:
        probability = event.get("probability")
        if isinstance(probability, (int, float)):
            value = float(probability)
            self.best_probability = (
                value
                if self.best_probability is None
                else max(self.best_probability, value)
            )

    def increment(self, counter_name: str, amount: int = 1) -> None:
        self.counters[counter_name] = self.counters.get(counter_name, 0) + amount

    def set_counter(self, counter_name: str, value: int) -> None:
        self.counters[counter_name] = value

    def counter(self, counter_name: str) -> int:
        return self.counters.get(counter_name, 0)

    def format_info(
        self,
        *,
        counter_labels: Mapping[str, str],
        include_best_probability: bool = False,
        include_current_target: bool = False,
    ) -> str:
        parts = [f"Progress: {self.done:,}/{self.total:,}"]
        for counter_name, label in counter_labels.items():
            parts.append(f"{label}: {self.counter(counter_name):,}")
        if include_best_probability and self.best_probability is not None:
            parts.append(f"Best P: {self.best_probability:.4f}")
        if include_current_target and self.current_target:
            parts.append(f"Target: {self.current_target}")
        return " | ".join(parts)


def _event_extra(event: Mapping[str, object]) -> Mapping[str, object]:
    extra = event.get("extra")
    return extra if isinstance(extra, Mapping) else {}


def _coerce_int(value: object, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _coerce_counter(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
