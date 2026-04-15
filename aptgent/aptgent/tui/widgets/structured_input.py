from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Button, Checkbox, Input, Static

from aptgent.domain.enums import Step


class StructuredInputSubmitted(Message):
    """Posted by structured input panels when the user submits."""

    def __init__(self, step: Step, data: dict) -> None:
        super().__init__()
        self.step = step
        self.data = data


class StructuredActionRequested(Message):
    """Posted by structured input panels for button actions."""

    def __init__(self, step: Step, action: str) -> None:
        super().__init__()
        self.step = step
        self.action = action


class CheckboxPanel(Vertical):
    """Inline widget for selecting mutation sites via checkboxes."""

    DEFAULT_CSS = """
    CheckboxPanel {
        background: $surface-darken-2;
        border: solid $primary;
        padding: 1 2;
        margin: 1 0;
        width: 95%;
        height: auto;
        max-height: 15;
    }
    """

    def __init__(self, sequence: str, proposed_sites: list[int], **kwargs) -> None:
        super().__init__(**kwargs)
        self.sequence = sequence
        self.proposed_sites = proposed_sites
        self.checkboxes: list[Checkbox] = []

    def compose(self) -> ComposeResult:
        yield Static("Select mutation sites:", classes="title")
        with Vertical(classes="checkbox-grid"):
            for pos in range(len(self.sequence)):
                cb = Checkbox(
                    f"Position {pos} ({self.sequence[pos]})",
                    value=(pos in self.proposed_sites),
                )
                self.checkboxes.append(cb)
                yield cb
        yield Button("Confirm Selection", id="btn-confirm-sites", variant="success")

    def get_selected(self) -> list[int]:
        return [i for i, cb in enumerate(self.checkboxes) if cb.value]

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-confirm-sites":
            self.post_message(
                StructuredInputSubmitted(
                    Step.SITE_PROPOSAL,
                    {"selected_sites": self.get_selected()},
                )
            )


class SpecificityPanel(Vertical):
    """Inline widget for specificity filter: analog input + skip/run buttons."""

    DEFAULT_CSS = """
    SpecificityPanel {
        background: $surface-darken-2;
        border: solid $primary;
        padding: 1 2;
        margin: 1 0;
        width: 95%;
        height: auto;
    }
    """

    def __init__(self, target_name: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self.target_name = target_name

    def compose(self) -> ComposeResult:
        yield Static("Specificity Filter", classes="title")
        if self.target_name:
            yield Static(f"Target molecule: {self.target_name}", classes="info-text")
        yield Static(
            "Enter analog molecules (comma-separated names or SMILES), "
            "or let the LLM suggest them.",
            classes="info-text",
        )
        yield Input(
            id="analog-input",
            placeholder="e.g. adenine, hypoxanthine",
        )
        with Horizontal():
            yield Button("Suggest Analogs", id="btn-suggest-analogs", variant="primary")
            yield Button("Run Filter", id="btn-run-filter", variant="warning")
            yield Button("Skip", id="btn-skip-filter")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "btn-suggest-analogs":
            self.post_message(
                StructuredActionRequested(Step.SPECIFICITY_FILTER, "suggest")
            )
        elif btn_id == "btn-run-filter":
            analogs = self.query_one("#analog-input", Input).value.strip()
            self.post_message(
                StructuredInputSubmitted(
                    Step.SPECIFICITY_FILTER,
                    {"action": "run", "analogs_text": analogs},
                )
            )
        elif btn_id == "btn-skip-filter":
            self.post_message(
                StructuredInputSubmitted(
                    Step.SPECIFICITY_FILTER,
                    {"action": "skip"},
                )
            )


class DockingParamPanel(Vertical):
    """Inline widget for docking configuration parameters."""

    DEFAULT_CSS = """
    DockingParamPanel {
        background: $surface-darken-2;
        border: solid $primary;
        padding: 1 2;
        margin: 1 0;
        width: 95%;
        height: auto;
    }
    DockingParamPanel > Input {
        margin-bottom: 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("Docking Configuration", classes="title")
        yield Static(f"Machine: {self._machine_info()}", classes="info-text")
        yield Static("Time budget (hours):", classes="info-text")
        yield Input(id="dock-time-budget", placeholder="e.g. 4")
        yield Button("Get LLM Recommendation", id="btn-dock-recommend", variant="primary")
        yield Static("", id="dock-recommendation-text", classes="info-text")
        yield Static("Top-k candidates to dock:", classes="info-text")
        yield Input(id="dock-top-k", placeholder="e.g. 10")
        yield Static("Receptor PDBQT file path:", classes="info-text")
        yield Input(id="dock-receptor", placeholder="/path/to/receptor.pdbqt")
        yield Static("Grid box center (x, y, z):", classes="info-text")
        with Horizontal():
            yield Input(id="dock-cx", placeholder="0.0")
            yield Input(id="dock-cy", placeholder="0.0")
            yield Input(id="dock-cz", placeholder="0.0")
        yield Static("Grid box size (x, y, z):", classes="info-text")
        with Horizontal():
            yield Input(id="dock-sx", placeholder="20.0")
            yield Input(id="dock-sy", placeholder="20.0")
            yield Input(id="dock-sz", placeholder="20.0")
        yield Button("Submit & Continue", id="btn-submit-dock", variant="success")

    @staticmethod
    def _machine_info() -> str:
        import os
        try:
            import psutil
            mem = round(psutil.virtual_memory().total / (1024 ** 3), 2)
            return f"CPUs: {os.cpu_count() or '?'}  |  Memory: {mem} GB"
        except Exception:
            return f"CPUs: {os.cpu_count() or '?'}"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-dock-recommend":
            budget = self.query_one("#dock-time-budget", Input).value.strip()
            self.post_message(
                StructuredActionRequested(
                    Step.DOCKING_SELECTION,
                    f"recommend:{budget}",
                )
            )
        elif event.button.id == "btn-submit-dock":
            data = self._collect_data()
            self.post_message(
                StructuredInputSubmitted(Step.DOCKING_SELECTION, data)
            )

    def _collect_data(self) -> dict:
        def fv(widget_id: str) -> float | None:
            try:
                return float(self.query_one(f"#{widget_id}", Input).value.strip())
            except (ValueError, AttributeError):
                return None

        cx, cy, cz = fv("dock-cx"), fv("dock-cy"), fv("dock-cz")
        sx, sy, sz = fv("dock-sx"), fv("dock-sy"), fv("dock-sz")

        budget_str = self.query_one("#dock-time-budget", Input).value.strip()
        top_k_str = self.query_one("#dock-top-k", Input).value.strip()
        receptor = self.query_one("#dock-receptor", Input).value.strip()

        return {
            "time_budget": int(budget_str) if budget_str.isdigit() else None,
            "top_k": int(top_k_str) if top_k_str.isdigit() else 0,
            "receptor_path": receptor or None,
            "grid_center": [cx, cy, cz] if all(v is not None for v in (cx, cy, cz)) else None,
            "grid_size": [sx, sy, sz] if all(v is not None for v in (sx, sy, sz)) else None,
        }

    def set_recommendation(self, top_k: int, reason: str) -> None:
        self.query_one("#dock-top-k", Input).value = str(top_k)
        self.query_one("#dock-recommendation-text", Static).update(
            f"LLM recommends top {top_k}. {reason}"
        )
