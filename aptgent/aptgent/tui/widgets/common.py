from __future__ import annotations

from textual.widgets import Static

from aptgent.domain.enums import Step

_STEP_ORDER = [
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

_STEP_SHORT_NAMES: dict[Step, str] = {
    Step.INTAKE: "Intake",
    Step.SECONDARY_STRUCTURE: "Structure",
    Step.SITE_PROPOSAL: "Sites",
    Step.CANDIDATE_ENUMERATION: "Enum",
    Step.PRIMARY_SCORING: "Score",
    Step.SPECIFICITY_FILTER: "Specificity",
    Step.DOCKING_SELECTION: "DockSel",
    Step.DOCKING_RUN: "Dock",
    Step.SPATIAL_RANK: "Spatial",
    Step.FINAL_REPORT: "Report",
}


class StepProgressBar(Static):
    """Compact progress indicator showing step numbers with status markers."""

    STEPS = _STEP_ORDER

    def __init__(self, current_step: Step, **kwargs) -> None:
        super().__init__("", **kwargs)
        self.current_step = current_step

    def on_mount(self) -> None:
        self.update_display()

    def set_step(self, step: Step) -> None:
        self.current_step = step
        self.update_display()

    def update_display(self) -> None:
        current_idx = -1
        for i, s in enumerate(self.STEPS):
            if s == self.current_step:
                current_idx = i
                break

        parts: list[str] = []
        for i, s in enumerate(self.STEPS):
            name = _STEP_SHORT_NAMES.get(s, s.value)
            num = i + 1
            if i < current_idx:
                parts.append(f"[green]✓ {num}.{name}[/]")
            elif i == current_idx:
                parts.append(f"[bold white on $primary]▶ {num}.{name}[/]")
            else:
                parts.append(f"[dim]{num}.{name}[/]")

        self.update(" │ ".join(parts))


class StatusPanel(Static):
    """Display current run ID and status."""

    def __init__(self, run_id: str, status: str, **kwargs) -> None:
        super().__init__("", **kwargs)
        self.run_id = run_id
        self.status = status

    def set_status(self, run_id: str, status: str) -> None:
        self.run_id = run_id
        self.status = status
        self.update_display()

    def update_display(self) -> None:
        if not self.run_id:
            self.update("[dim]No active run[/]")
            return
        status_style = {
            "running": "[green]●[/] Running",
            "paused": "[yellow]◉[/] Paused",
            "completed": "[green]✓[/] Completed",
            "error": "[red]✗[/] Error",
            "pending": "[dim]○[/] Pending",
        }.get(self.status, self.status)
        self.update(f"[bold]{self.run_id}[/]  {status_style}")
