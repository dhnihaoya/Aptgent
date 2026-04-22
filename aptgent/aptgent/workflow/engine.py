from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from aptgent.domain.enums import Status, Step
from aptgent.workflow.persistence import Persistence
from aptgent.workflow.state import RunState

TRANSITIONS: dict[Step, list[Step]] = {
    Step.INTAKE: [Step.INTAKE, Step.SECONDARY_STRUCTURE],
    Step.SECONDARY_STRUCTURE: [Step.SITE_PROPOSAL],
    Step.SITE_PROPOSAL: [Step.CANDIDATE_ENUMERATION],
    Step.CANDIDATE_ENUMERATION: [Step.PRIMARY_SCORING],
    Step.PRIMARY_SCORING: [Step.SPECIFICITY_FILTER],
    Step.SPECIFICITY_FILTER: [Step.DOCKING_SELECTION],
    Step.DOCKING_SELECTION: [Step.DOCKING_RUN],
    Step.DOCKING_RUN: [Step.SPATIAL_RANK],
    Step.SPATIAL_RANK: [Step.FINAL_REPORT],
    Step.FINAL_REPORT: [],
}


class WorkflowEngine:
    def __init__(
        self,
        persistence: Persistence,
        tools_config: dict[str, Any] | None = None,
        llm_config: dict[str, Any] | None = None,
    ) -> None:
        self.persistence = persistence
        self.tools_config = tools_config
        self.llm_config = llm_config

    def create_run(self, run_id: str | None = None) -> RunState:
        if run_id is None:
            import uuid

            run_id = uuid.uuid4().hex[:12]
        return self.persistence.init_run(run_id)

    def load_run(self, run_id: str) -> RunState | None:
        return self.persistence.load(run_id)

    def transition_to(
        self,
        state: RunState,
        next_step: Step,
        metadata: Optional[dict[str, Any]] = None,
    ) -> RunState:
        allowed = TRANSITIONS.get(state.current_step, [])
        if next_step not in allowed:
            raise ValueError(
                f"Invalid transition from {state.current_step.value} to {next_step.value}. "
                f"Allowed: {[s.value for s in allowed]}"
            )
        state.current_step = next_step
        state.status = Status.RUNNING
        state.error_info = None
        state.step_timestamps[next_step.value] = datetime.now(timezone.utc).isoformat()
        self.persistence.save(state)
        self.persistence.append_log(
            state.run_id,
            {
                "event": "transition",
                "to_step": next_step.value,
                "metadata": metadata or {},
            },
        )
        return state

    def rewind_to(
        self,
        state: RunState,
        step: Step,
        metadata: Optional[dict[str, Any]] = None,
    ) -> RunState:
        state.current_step = step
        state.status = Status.RUNNING
        state.error_info = None
        state.step_timestamps[step.value] = datetime.now(timezone.utc).isoformat()
        self.persistence.save(state)
        self.persistence.append_log(
            state.run_id,
            {
                "event": "rewind",
                "to_step": step.value,
                "metadata": metadata or {},
            },
        )
        return state

    def pause(
        self,
        state: RunState,
        reason: str,
        pending_input: Optional[dict[str, Any]] = None,
    ) -> RunState:
        state.status = Status.PAUSED
        state.pending_input = pending_input or {"reason": reason}
        self.persistence.save(state)
        self.persistence.append_log(
            state.run_id,
            {"event": "pause", "reason": reason, "pending_input": pending_input},
        )
        return state

    def resume(self, state: RunState) -> RunState:
        if state.status != Status.PAUSED:
            return state
        state.status = Status.RUNNING
        state.pending_input = None
        self.persistence.save(state)
        self.persistence.append_log(state.run_id, {"event": "resume"})
        return state

    def complete(self, state: RunState) -> RunState:
        state.status = Status.COMPLETED
        state.step_timestamps["_completed"] = datetime.now(timezone.utc).isoformat()
        self.persistence.save(state)
        self.persistence.append_log(state.run_id, {"event": "complete"})
        try:
            from aptgent.workflow.run_card import write_run_card
            write_run_card(
                state, self.persistence,
                tools_config=self.tools_config,
                llm_config=self.llm_config,
            )
        except Exception:
            import logging
            logging.getLogger(__name__).warning("Failed to write run card", exc_info=True)
        return state

    def fail(self, state: RunState, error: str) -> RunState:
        state.status = Status.ERROR
        state.error_info = {"message": error}
        self.persistence.save(state)
        self.persistence.append_log(state.run_id, {"event": "error", "message": error})
        return state
