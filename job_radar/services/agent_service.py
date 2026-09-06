"""Application service for the bounded, resumable LangGraph workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import StateSnapshot
from pydantic import BaseModel, Field

from job_radar.agent.actions import execute_action
from job_radar.agent.controllers import Controller, RuleBasedController
from job_radar.agent.graph import build_agent_graph
from job_radar.agent.models import AgentLimits, AgentState
from job_radar.infra.logging import configure_logging, new_run_id
from job_radar.infra.paths import DEFAULT_CHECKPOINT_DB_PATH, DEFAULT_DB_PATH
from job_radar.profile.models import UserProfile
from job_radar.tools.executor import ToolExecutor
from job_radar.services.persistence import JobPersistenceService
from job_radar.services.runtime import create_real_agent_runtime


class DecisionTraceEntry(BaseModel):
    step: int
    available_actions: list[str] = Field(default_factory=list)
    selected_action: str
    rationale: str
    state_summary: dict[str, Any] = Field(default_factory=dict)


class AgentServiceResult(BaseModel):
    state: AgentState
    decision_trace: list[DecisionTraceEntry] = Field(default_factory=list)
    run_id: str | None = None
    checkpoint_id: str | None = None
    interrupted: bool = False


class CheckpointHistoryEntry(BaseModel):
    """Public, stable representation of one LangGraph state snapshot."""

    run_id: str
    checkpoint_id: str
    parent_checkpoint_id: str | None = None
    created_at: str | None = None
    next_nodes: list[str] = Field(default_factory=list)
    state: AgentState


@dataclass
class AgentService:
    controller: Controller
    executor: ToolExecutor
    limits: AgentLimits = field(default_factory=AgentLimits)
    max_steps: int | None = None
    checkpoint_path: Path = DEFAULT_CHECKPOINT_DB_PATH
    db_path: Path = DEFAULT_DB_PATH
    persistence_service: JobPersistenceService | None = None

    def __post_init__(self) -> None:
        if self.persistence_service is None:
            self.persistence_service = JobPersistenceService(self.db_path)

    def run(self, profile: UserProfile, *, initial_state: AgentState | None = None,
            run_id: str | None = None, pause_after_action: bool = False) -> AgentServiceResult:
        run_id = run_id or configure_logging(new_run_id())
        limits = self.limits.model_copy(update={"max_steps": self.max_steps or self.limits.max_steps})
        config = {"configurable": {"thread_id": run_id}}
        with SqliteSaver.from_conn_string(str(self.checkpoint_path)) as saver:
            graph = self._build_graph(saver, limits=limits, pause_after_action=pause_after_action)
            result = graph.invoke({"agent_state": initial_state or AgentState(), "profile": profile,
                                   "step": 0, "decision_trace": [], "current_action": None,
                                   "current_stop_reason": None}, config)
            snapshot = graph.get_state(config)
            return _result_from_graph(result, run_id, checkpoint_id=_checkpoint_id(snapshot),
                                      interrupted=bool(snapshot.next))

    def resume(self, run_id: str, *, pause_after_action: bool = False) -> AgentServiceResult:
        """Continue from the latest checkpoint for ``run_id``."""
        configure_logging(run_id)
        config = {"configurable": {"thread_id": run_id}}
        limits = self.limits.model_copy(update={"max_steps": self.max_steps or self.limits.max_steps})
        with SqliteSaver.from_conn_string(str(self.checkpoint_path)) as saver:
            graph = self._build_graph(saver, limits=limits, pause_after_action=pause_after_action)
            if not graph.get_state(config).values:
                raise KeyError(f"No checkpoint exists for run_id={run_id!r}")
            result = graph.invoke(None, config)
            snapshot = graph.get_state(config)
            return _result_from_graph(result, run_id, checkpoint_id=_checkpoint_id(snapshot),
                                      interrupted=bool(snapshot.next))

    def state_history(self, run_id: str) -> list[CheckpointHistoryEntry]:
        """Return public checkpoint snapshots, newest checkpoint first."""
        config = {"configurable": {"thread_id": run_id}}
        limits = self.limits.model_copy(update={"max_steps": self.max_steps or self.limits.max_steps})
        with SqliteSaver.from_conn_string(str(self.checkpoint_path)) as saver:
            graph = self._build_graph(saver, limits=limits)
            return [_history_entry(snapshot, run_id) for snapshot in graph.get_state_history(config)]

    def replay_from_checkpoint(self, run_id: str, checkpoint_id: str, *,
                               pause_after_action: bool = False) -> AgentServiceResult:
        """Run exactly the next action from a selected checkpoint.

        Replay deliberately compiles a paused graph, regardless of the
        caller's normal run preference.  LangGraph resumes at the selected
        checkpoint, executes the pending decision/action pair when needed,
        persists that action's state, and interrupts before routing onward.
        """
        configure_logging(run_id)
        config = {"configurable": {"thread_id": run_id, "checkpoint_id": checkpoint_id}}
        limits = self.limits.model_copy(update={"max_steps": self.max_steps or self.limits.max_steps})
        with SqliteSaver.from_conn_string(str(self.checkpoint_path)) as saver:
            # A replay is always single-step.  Do not use the caller's
            # ``pause_after_action`` value here: the frontend's replay
            # control must never start a complete workflow branch.
            graph = self._build_graph(saver, limits=limits, pause_after_action=True)
            snapshot = graph.get_state(config)
            if _checkpoint_id(snapshot) != checkpoint_id:
                raise KeyError(f"No checkpoint {checkpoint_id!r} exists for run_id={run_id!r}")
            result = graph.invoke(None, config)
            latest = graph.get_state({"configurable": {"thread_id": run_id}})
            return _result_from_graph(result, run_id, checkpoint_id=_checkpoint_id(latest),
                                      interrupted=bool(latest.next))

    def _build_graph(self, saver: SqliteSaver, *, limits: AgentLimits,
                     pause_after_action: bool = False):
        return build_agent_graph(controller=self.controller, executor=self.executor, limits=limits,
                                 action_runner=execute_action, checkpointer=saver,
                                 pause_after_action=pause_after_action,
                                 persistence_service=self.persistence_service)


def _result_from_graph(result: dict[str, object], run_id: str, *, checkpoint_id: str | None = None,
                       interrupted: bool = False) -> AgentServiceResult:
    state = result["agent_state"]
    return AgentServiceResult(
        state=state if isinstance(state, AgentState) else AgentState.model_validate(state),
        decision_trace=[DecisionTraceEntry.model_validate(item) for item in result.get("decision_trace", [])],
        run_id=run_id,
        checkpoint_id=checkpoint_id,
        interrupted=interrupted or bool(result.get("__interrupt__")),
    )


def _checkpoint_id(snapshot: StateSnapshot) -> str | None:
    return snapshot.config.get("configurable", {}).get("checkpoint_id")


def _history_entry(snapshot: StateSnapshot, run_id: str) -> CheckpointHistoryEntry:
    values = snapshot.values if isinstance(snapshot.values, dict) else {}
    parent = snapshot.parent_config or {}
    parent_checkpoint_id = parent.get("configurable", {}).get("checkpoint_id")
    return CheckpointHistoryEntry(
        run_id=run_id,
        checkpoint_id=_checkpoint_id(snapshot) or "",
        parent_checkpoint_id=parent_checkpoint_id,
        created_at=snapshot.created_at,
        next_nodes=list(snapshot.next),
        state=values.get("agent_state", AgentState()),
    )


def create_rule_based_real_agent_service(*, db_path: Path = DEFAULT_DB_PATH,
                                         limits: AgentLimits | None = None) -> AgentService:
    runtime = create_real_agent_runtime()
    return AgentService(controller=RuleBasedController(), executor=runtime.executor,
                        limits=limits or AgentLimits(),
                        persistence_service=JobPersistenceService(db_path))


__all__ = ["AgentService", "AgentServiceResult", "CheckpointHistoryEntry", "DecisionTraceEntry",
           "create_rule_based_real_agent_service"]
