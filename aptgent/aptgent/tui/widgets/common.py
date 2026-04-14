from __future__ import annotations

from textual.widgets import Label, Static

from aptgent.domain.enums import Step


class StepProgressBar(Static):
    """Simple text-based progress indicator."""

    STEPS = [
        Step.INTAKE,
        Step.SECONDARY_STRUCTURE,
        Step.SITE_PROPOSAL,
        Step.CANDIDATE_ENUMERATION,
        Step.PRIMARY_SCORING,
        Step.SPECIFICITY_FILTER,
        Step.DOCKING_SELECTION,
        Step.DOCKING_RUN,
        Step.SPATIAL_RANK,
        Step.FINAL_REPORT,
    ]

    def __init__(self, current_step: Step, **kwargs):
        super().__init__("", **kwargs)
        self.current_step = current_step

    def on_mount(self) -> None:
        self.update_display()

    def set_step(self, step: Step) -> None:
        self.current_step = step
        self.update_display()

    def update_display(self) -> None:
        parts = []
        for s in self.STEPS:
            name = s.value.replace("_", " ").title()
            if s == self.current_step:
                parts.append(f"[ {name} ]")
            else:
                parts.append(name)
        self.update("  >  ".join(parts))


class StatusPanel(Static):
    """Display current run status."""

    def __init__(self, run_id: str, status: str, **kwargs):
        super().__init__("", **kwargs)
        self.run_id = run_id
        self.status = status

    def set_status(self, run_id: str, status: str) -> None:
        self.run_id = run_id
        self.status = status
        self.update_display()

    def update_display(self) -> None:
        self.update(f"Run: {self.run_id}  |  Status: {self.status}")
