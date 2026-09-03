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
from job_radar.infra.logging import configure_logging, get_logger, new_run_id

logger = get_logger(__name__)


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
        run_id = configure_logging(new_run_id())
        logger.info("agent_run_start run_id=%s", run_id)
        trace: list[DecisionTraceEntry] = []
        step_limit = self.max_steps or self.limits.max_steps

        for step in range(1, step_limit + 1):
            context = DecisionContext(
                state=state,
                limits=self.limits,
                profile=profile,
            )
            action = self.controller.decide(context)
            logger.info(
                "agent_decision run_id=%s step=%s round_index=%s action=%s",
                run_id, step, state.round_index, action.action,
            )
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
                logger.info("agent_stop run_id=%s round_index=%s stop_reason=%s", run_id, state.round_index, state.stop_reason)
                return AgentServiceResult(state=state, decision_trace=trace)

            next_state = execute_action(action, state, self.executor, self.limits, profile=profile)
            if next_state == state:
                raise RuntimeError(
                    f"Agent action {action.action!r} did not change State; refusing to repeat it"
                )
            state = next_state

        state = state.model_copy(update={"stop_reason": "max_steps reached"})
        logger.info("agent_stop run_id=%s round_index=%s stop_reason=max_steps reached", run_id, state.round_index)
        return AgentServiceResult(state=state, decision_trace=trace)

    @staticmethod
    def _state_summary(state: AgentState) -> dict[str, Any]:
        return {
            "round_index": state.round_index,
            "stop_reason": state.stop_reason,
            "candidate_sources": len(state.candidate_sources),
            "selected_sources": len(state.selected_sources),
            "acquired_pages": len(state.acquired_pages),
            "job_detail_pages": len(state.job_detail_pages),
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
