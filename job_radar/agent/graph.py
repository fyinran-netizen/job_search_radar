"""LangGraph adapter around the deterministic scheduler and action handlers."""

from __future__ import annotations

from typing import Callable, Literal, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from job_radar.agent.actions import AgentAction, execute_action
from job_radar.agent.action_names import AGENT_ACTION_NAMES, AgentActionName
from job_radar.agent.controllers.context import ExecutionMetrics, LastActionOutcome, build_scheduling_context
from job_radar.agent.controllers.features import build_scheduling_features
from job_radar.agent.controllers.outcome import build_outcome
from job_radar.agent.controllers.scheduler import schedule_with_scores
from job_radar.agent.models import AgentLimits, AgentState
from job_radar.agent.policies.availability import available_actions
from job_radar.infra.logging import get_logger
from job_radar.profile.models import UserProfile
from job_radar.tools.executor import ToolExecutor
from job_radar.infra.storage.repository import UpsertJobsResult
from job_radar.services.persistence import JobPersistenceService


logger = get_logger(__name__)


class AgentGraphState(TypedDict, total=False):
    agent_state: AgentState
    profile: UserProfile
    step: int
    current_action: AgentActionName | None
    current_stop_reason: str | None
    decision_trace: list[dict[str, object]]
    last_outcome: LastActionOutcome | None
    persistence_result: UpsertJobsResult


ActionExecutor = Callable[..., AgentState]
AgentGraphRoute = AgentActionName | Literal["__end__"]


def build_agent_graph(*, executor: ToolExecutor, limits: AgentLimits,
                      action_runner: ActionExecutor = execute_action,
                      checkpointer: SqliteSaver, pause_after_action: bool = False,
                      persistence_service: JobPersistenceService | None = None):
    graph = StateGraph(AgentGraphState)

    def decide_node(state: AgentGraphState) -> dict[str, object]:
        # Checkpoint deserialization may return nested dictionaries.  Validate
        # once at the graph boundary so controllers and actions always receive
        # the declared Pydantic model.
        agent_state = _validated_agent_state(state["agent_state"])
        step = int(state.get("step", 0))
        if step >= limits.max_steps or agent_state.execution_step_count >= limits.max_steps:
            logger.info(
                "run_stop search_round_count=%s stop_reason=%s",
                agent_state.search_round_count,
                "max_steps",
            )
            return {"agent_state": agent_state.model_copy(update={"stop_reason": "max_steps"}),
                    "current_action": None, "current_stop_reason": None}
        available = available_actions(
                agent_state,
                limits,
                profile=state.get("profile"),
        )
        context = build_scheduling_context(
            agent_state, limits, available,
            last_outcome=state.get("last_outcome"),
        )
        features = build_scheduling_features(
            agent_state,
            limits,
            context,
            state.get("last_outcome"),
        )
        action, action_scores = schedule_with_scores(context, features)
        trace = [*state.get("decision_trace", [])]
        trace.append({"step": step + 1, "available_actions": list(context.specific.available_actions),
                      "selected_action": action.action, "rationale": action.rationale,
                      "action_scores": [item.model_dump() for item in action_scores],
                      "state_summary": _state_summary(agent_state)})
        return {"step": step + 1, "current_action": action.action,
                "current_stop_reason": getattr(action, "stop_reason", None), "decision_trace": trace}

    def route(state: AgentGraphState) -> AgentGraphRoute:
        return state.get("current_action") or END

    def persist_node(state: AgentGraphState) -> dict[str, object]:
        if persistence_service is None:
            return {"persistence_result": UpsertJobsResult()}
        return {"persistence_result": persistence_service.persist(state["agent_state"])}

    graph.add_node("decide", decide_node)
    graph.add_node("persist", persist_node)
    graph.add_edge(START, "decide")
    action_names = AGENT_ACTION_NAMES
    destinations = {name: name for name in action_names} | {END: END}
    graph.add_conditional_edges("decide", route, destinations)

    for action_name in action_names:
        def action_node(
            state: AgentGraphState,
            name: AgentActionName = action_name,
        ) -> dict[str, object]:
            current = _validated_agent_state(state["agent_state"])
            trace = state.get("decision_trace", [])
            rationale = str(trace[-1].get("rationale", name)) if trace else name
            action = AgentAction(action=name, rationale=rationale,
                                 stop_reason=(state.get("current_stop_reason") if name == "stop" else None))
            event_start = len(executor.events)
            next_state = action_runner(action, current, executor, limits, profile=state.get("profile"))
            if next_state == current:
                raise RuntimeError(f"Agent action {name!r} did not change State; refusing to repeat it")
            events = executor.events[event_start:]
            outcome = build_outcome(
                name,
                current,
                next_state,
                execution=_execution_metrics(events),
            )
            if name == "stop":
                logger.info(
                    "run_stop search_round_count=%s stop_reason=%s",
                    next_state.search_round_count,
                    next_state.stop_reason,
                )
            return {"agent_state": next_state, "last_outcome": outcome}

        graph.add_node(action_name, action_node)
        graph.add_edge(action_name, "persist" if action_name == "stop" else "decide")
    graph.add_edge("persist", END)

    return graph.compile(checkpointer=checkpointer,
                         interrupt_after=list(action_names) if pause_after_action else None)


def _validated_agent_state(value: object) -> AgentState:
    return value if isinstance(value, AgentState) else AgentState.model_validate(value or {})


def _execution_metrics(events: list[object]) -> ExecutionMetrics:
    elapsed = sum(float(getattr(event, "elapsed_ms", 0.0)) for event in events)
    metric_values = {
        name: [getattr(event, name, None) for event in events]
        for name in ("llm_calls", "input_tokens", "output_tokens", "total_tokens")
    }
    values = {
        name: (sum(items) if items and all(item is not None for item in items) else None)
        for name, items in metric_values.items()
    }
    return ExecutionMetrics(elapsed_ms=elapsed, **values)


def _state_summary(state: AgentState) -> dict[str, object]:
    return {"search_round_count": state.search_round_count, "stop_reason": state.stop_reason,
            "candidate_sources": len(state.candidate_sources),
            "acquisition_queue": len(state.acquisition_queue),
            "acquired_pages": len(state.acquired_pages), "job_detail_pages": len(state.job_detail_pages),
            "prepared_jobs": len(state.prepared_jobs), "understanding_records": len(state.understanding_records),
            "match_assessments": len(state.match_assessments), "errors": len(state.errors)}
