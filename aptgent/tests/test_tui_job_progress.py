from __future__ import annotations

from aptgent.tui.steps.job_progress import JobProgressTracker


def test_job_progress_tracker_updates_progress_counters_and_target():
    tracker = JobProgressTracker()

    tracker.apply_progress(
        {
            "type": "progress",
            "done": 7,
            "total": 12,
            "extra": {"kept": 3, "removed": 2, "current_target": "caffeine"},
        },
        counter_fields=("kept", "removed"),
    )

    assert tracker.done == 7
    assert tracker.total == 12
    assert tracker.counter("kept") == 3
    assert tracker.counter("removed") == 2
    assert tracker.current_target == "caffeine"
    assert tracker.format_info(
        counter_labels={"kept": "Kept", "removed": "Removed"},
        include_current_target=True,
    ) == "Progress: 7/12 | Kept: 3 | Removed: 2 | Target: caffeine"


def test_job_progress_tracker_tracks_best_probability_and_hits():
    tracker = JobProgressTracker(total=256)

    tracker.apply_progress(
        {"type": "progress", "done": 128, "total": 256, "extra": {"binding": 1}},
        counter_fields=("binding",),
    )
    tracker.apply_probability_hit({"type": "hit", "probability": 0.75})
    tracker.apply_probability_hit({"type": "hit", "probability": 0.91})
    tracker.increment("binding")

    assert tracker.format_info(
        counter_labels={"binding": "Hits"},
        include_best_probability=True,
    ) == "Progress: 128/256 | Hits: 2 | Best P: 0.9100"


def test_job_progress_tracker_keeps_counters_monotonic_for_late_progress():
    tracker = JobProgressTracker()
    tracker.set_counter("binding", 10)

    tracker.apply_progress(
        {"type": "progress", "done": 128, "total": 256, "extra": {"binding": 3}},
        counter_fields=("binding",),
    )

    assert tracker.counter("binding") == 10


def test_job_progress_tracker_coerces_float_counter_values():
    tracker = JobProgressTracker()

    tracker.apply_progress(
        {"type": "progress", "done": 128, "total": 256, "extra": {"binding": 5.0}},
        counter_fields=("binding",),
    )

    assert tracker.counter("binding") == 5


def test_job_progress_tracker_reset_clears_summary_state():
    tracker = JobProgressTracker(done=5, total=10, counters={"kept": 2})
    tracker.best_probability = 0.8
    tracker.current_target = "old"

    tracker.reset(total=20)

    assert tracker.done == 0
    assert tracker.total == 20
    assert tracker.counters == {}
    assert tracker.best_probability is None
    assert tracker.current_target == ""
