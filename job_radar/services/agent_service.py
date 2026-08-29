"""Application service for running the bounded agent action loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from job_radar.agent.actions import execute_action
from job_radar.agent.controllers import Controller, DecisionContext, RuleBasedController
from job_radar.agent.models import AgentLimits, AgentState
from job_radar.infra.paths import DEFAULT_DB_PATH
from job_radar.profile.models import UserProfile
from job_radar.tools.executor import ToolExecutor
from job_radar.tools.web_search.search_strategy import SearchPlanBuilder


class DecisionTraceEntry(BaseModel):
    """One controller decision and the state observed around it."""

    step: int
    available_actions: list[str] = Field(default_factory=list)
    selected_action: str
    rationale: str
    state_summary: dict[str, Any] = Field(default_factory=dict)


class AgentServiceResult(BaseModel):
    """Final state and trace produced by one agent loop."""

    state: AgentState
    decision_trace: list[DecisionTraceEntry] = Field(default_factory=list)


@dataclass
class AgentService:
    """Run controller decisions through the existing bounded action handlers."""

    controller: Controller
    executor: ToolExecutor
    limits: AgentLimits = field(default_factory=AgentLimits)
    max_steps: int | None = None

    def run(
        self,
        profile: UserProfile,
        *,
        initial_state: AgentState | None = None,
    ) -> AgentServiceResult:
        """Run until the injected controller selects ``stop``."""

        state = initial_state or AgentState()
        if state.search_plan is None:
            state = state.model_copy(update={"search_plan": SearchPlanBuilder().build(profile)})

        trace: list[DecisionTraceEntry] = []
        step_limit = self.max_steps or (self.limits.max_rounds * 7 + 1)

        for step in range(1, step_limit + 1):
            context = DecisionContext(
                state=state,
                limits=self.limits,
                profile=profile,
            )
            action = self.controller.decide(context)
            trace.append(
                DecisionTraceEntry(
                    step=step,
                    available_actions=list(context.available_actions),
                    selected_action=action.action,
                    rationale=action.rationale,
                    state_summary=self._state_summary(state),
                )
            )

            if action.action == "stop":
                state = execute_action(action, state, self.executor, self.limits, profile=profile)
                return AgentServiceResult(state=state, decision_trace=trace)

            next_state = execute_action(action, state, self.executor, self.limits, profile=profile)
            if next_state == state:
                raise RuntimeError(
                    f"Agent action {action.action!r} did not change State; refusing to repeat it"
                )
            state = next_state

        raise RuntimeError(f"Agent loop exceeded its bounded step limit ({step_limit})")

    @staticmethod
    def _state_summary(state: AgentState) -> dict[str, Any]:
        return {
            "round_index": state.round_index,
            "stop_reason": state.stop_reason,
            "candidate_sources": len(state.candidate_sources),
            "selected_sources": len(state.selected_sources),
            "collected_pages": len(state.collected_pages),
            "processed_pages": len(state.processed_pages),
            "prepared_jobs": len(state.prepared_jobs),
            "understanding_records": len(state.understanding_records),
            "match_assessments": len(state.match_assessments),
            "errors": len(state.errors),
        }


def create_rule_based_real_agent_service(
    *,
    db_path: Path = DEFAULT_DB_PATH,
    limits: AgentLimits | None = None,
) -> AgentService:
    """Build the Streamlit runtime with a rule-based controller.

    The existing ingestion service remains the owner of real-tool wiring;
    this adapter only reuses that wiring and does not call its pipeline.
    """

    from job_radar.services.ingestion import IngestionService

    ingestion_service = IngestionService(db_path=db_path)
    executor = ingestion_service._create_real_tool_executor(  # noqa: SLF001
        ingestion_service._real_run_metadata(),  # noqa: SLF001
    )
    return AgentService(
        controller=RuleBasedController(),
        executor=executor,
        limits=limits or AgentLimits(),
    )


__all__ = ["AgentService", "AgentServiceResult", "DecisionTraceEntry", "create_rule_based_real_agent_service"]
