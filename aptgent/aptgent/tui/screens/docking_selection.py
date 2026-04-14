from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Input, Static

from aptgent.domain.models import DockingPlan
from aptgent.adapters.docking import HardwareProbeAdapter
from aptgent.llm.skills import DockingPlannerSkill


class DockingSelectionScreen(Screen):
    """Select top-k candidates for docking and configure docking parameters."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.probe = HardwareProbeAdapter()
        self.skill = DockingPlannerSkill()

    def compose(self) -> ComposeResult:
        yield self.app.progress_bar
        yield self.app.status_panel

        with Vertical(id="content-area"):
            yield Static("Step 7: Docking Selection", classes="title")
            yield Static("", id="machine-info", classes="info-text")
            yield Static("Enter time budget (hours):", classes="label")
            yield Input(id="time-budget", placeholder="e.g. 4")
            yield Button("Get LLM Recommendation", id="btn-recommend", variant="primary")
            yield Static("", id="recommendation-info")
            yield Static("Top-k to dock:", classes="label")
            yield Input(id="top-k", placeholder="e.g. 10")

            yield Static("Receptor PDBQT file path:", classes="label")
            yield Input(id="receptor-path", placeholder="/path/to/receptor.pdbqt")
            yield Static("Grid box center (x, y, z):", classes="label")
            yield Horizontal(
                Input(id="grid-cx", placeholder="0.0"),
                Input(id="grid-cy", placeholder="0.0"),
                Input(id="grid-cz", placeholder="0.0"),
            )
            yield Static("Grid box size (x, y, z):", classes="label")
            yield Horizontal(
                Input(id="grid-sx", placeholder="20.0"),
                Input(id="grid-sy", placeholder="20.0"),
                Input(id="grid-sz", placeholder="20.0"),
            )

            yield Static("", id="dock-status")

        with Horizontal(id="action-bar"):
            yield Button("Back", id="btn-back")
            yield Button("Continue", id="btn-continue", variant="success", disabled=True)

    def on_mount(self) -> None:
        profile = self.probe.probe()
        mem = profile.get("memory_gb")
        mem_str = f"{mem} GB" if mem else "unknown"
        info = (
            f"CPUs: {profile.get('cpu_count', 'unknown')}  |  "
            f"Memory: {mem_str}"
        )
        self.query_one("#machine-info", Static).update(info)
        self._machine_profile = profile

        state = self.app.current_state
        if state.docking_plan:
            plan = state.docking_plan
            if plan.time_budget is not None:
                self.query_one("#time-budget", Input).value = str(plan.time_budget)
            self.query_one("#top-k", Input).value = str(plan.recommended_top_k)
            if plan.receptor_path:
                self.query_one("#receptor-path", Input).value = plan.receptor_path
            if plan.grid_center:
                cx, cy, cz = plan.grid_center
                self.query_one("#grid-cx", Input).value = str(cx)
                self.query_one("#grid-cy", Input).value = str(cy)
                self.query_one("#grid-cz", Input).value = str(cz)
            if plan.grid_size:
                sx, sy, sz = plan.grid_size
                self.query_one("#grid-sx", Input).value = str(sx)
                self.query_one("#grid-sy", Input).value = str(sy)
                self.query_one("#grid-sz", Input).value = str(sz)
            self.query_one("#dock-status", Static).update("Plan already set.")
            self.query_one("#btn-continue", Button).disabled = False

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "btn-recommend":
            await self._recommend()
        elif btn_id == "btn-continue":
            self._save_and_continue()
        elif btn_id == "btn-back":
            self.app.pop_screen()

    async def _recommend(self) -> None:
        state = self.app.current_state
        candidates = state.candidates
        if not candidates:
            self.query_one("#dock-status", Static).update("No candidates available.")
            return

        budget_str = self.query_one("#time-budget", Input).value.strip()
        time_budget = int(budget_str) if budget_str.isdigit() else None

        self.query_one("#dock-status", Static).update("Asking LLM for recommendation...")
        try:
            result = self.skill.plan(
                candidate_count=len(candidates),
                machine_profile=self._machine_profile,
                time_budget_hours=time_budget,
            )
            top_k = result.get("recommended_top_k", 0)
            reason = result.get("reason", "")
            self.query_one("#top-k", Input).value = str(top_k)
            self.query_one("#recommendation-info", Static).update(
                f"LLM recommends top {top_k}. {reason}"
            )
            self.query_one("#dock-status", Static).update("Recommendation received.")
        except Exception as e:
            self.query_one("#dock-status", Static).update(f"Recommendation failed: {e}")

    def _parse_float(self, value: str) -> float | None:
        try:
            return float(value.strip())
        except (ValueError, AttributeError):
            return None

    def _save_and_continue(self) -> None:
        state = self.app.current_state
        budget_str = self.query_one("#time-budget", Input).value.strip()
        time_budget = int(budget_str) if budget_str.isdigit() else None

        top_k_str = self.query_one("#top-k", Input).value.strip()
        top_k = int(top_k_str) if top_k_str.isdigit() else 0

        receptor_path = self.query_one("#receptor-path", Input).value.strip() or None

        cx = self._parse_float(self.query_one("#grid-cx", Input).value)
        cy = self._parse_float(self.query_one("#grid-cy", Input).value)
        cz = self._parse_float(self.query_one("#grid-cz", Input).value)
        sx = self._parse_float(self.query_one("#grid-sx", Input).value)
        sy = self._parse_float(self.query_one("#grid-sy", Input).value)
        sz = self._parse_float(self.query_one("#grid-sz", Input).value)

        grid_center = [cx, cy, cz] if all(v is not None for v in (cx, cy, cz)) else None
        grid_size = [sx, sy, sz] if all(v is not None for v in (sx, sy, sz)) else None

        if top_k <= 0:
            self.query_one("#dock-status", Static).update("Please enter a valid top-k > 0.")
            return

        if not receptor_path:
            self.query_one("#dock-status", Static).update("Please provide a receptor PDBQT file path.")
            return

        if not grid_center or not grid_size:
            self.query_one("#dock-status", Static).update("Please provide grid box center and size (x, y, z).")
            return

        state.docking_plan = DockingPlan(
            machine_profile=self._machine_profile,
            time_budget=time_budget,
            recommended_top_k=top_k,
            reason=self.query_one("#recommendation-info", Static).renderable or "",
            receptor_path=receptor_path,
            grid_center=grid_center,
            grid_size=grid_size,
        )
        self.app.save_state()
        self.app.advance_step()
