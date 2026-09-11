"""LangGraph adapter around the existing controller and action handlers."""

from __future__ import annotations

from typing import Callable, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from job_radar.agent.actions import AgentAction, execute_action
from job_radar.agent.action_names import AGENT_ACTION_NAMES
from job_radar.agent.controllers import Controller, DecisionContext
from job_radar.agent.models import AgentLimits, AgentState
from job_radar.agent.policies.namespace import available_actions
from job_radar.profile.models import UserProfile
from job_radar.tools.executor import ToolExecutor
from job_radar.infra.storage.repository import UpsertJobsResult
from job_radar.services.persistence import JobPersistenceService


class AgentGraphState(TypedDict, total=False):
    agent_state: AgentState
    profile: UserProfile
    step: int
    current_action: str | None
    current_stop_reason: str | None
    decision_trace: list[dict[str, object]]
    persistence_result: UpsertJobsResult


ActionExecutor = Callable[..., AgentState]


def build_agent_graph(*, controller: Controller, executor: ToolExecutor, limits: AgentLimits,
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
        if step >= limits.max_steps:
            return {"agent_state": agent_state.model_copy(update={"stop_reason": "max_steps reached"}),
                    "current_action": None, "current_stop_reason": None}
        last_action = state.get("current_action")
        stage = last_action
        context = DecisionContext(
            state=agent_state,
            limits=limits,
            profile=state.get("profile"),
            available_actions=available_actions(
                agent_state,
                limits,
                profile=state.get("profile"),
                last_action=last_action,
                stage=stage,
            ),
            last_action=last_action,
            stage=stage,
        )
        action = controller.decide(context)
        trace = [*state.get("decision_trace", [])]
        trace.append({"step": step + 1, "available_actions": list(context.available_actions),
                      "selected_action": action.action, "rationale": action.rationale,
                      "state_summary": _state_summary(agent_state)})
        return {"step": step + 1, "current_action": action.action,
                "current_stop_reason": getattr(action, "stop_reason", None), "decision_trace": trace}

    def route(state: AgentGraphState) -> str:
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
        def action_node(state: AgentGraphState, name: str = action_name) -> dict[str, object]:
            current = _validated_agent_state(state["agent_state"])
            trace = state.get("decision_trace", [])
            rationale = str(trace[-1].get("rationale", name)) if trace else name
            action = AgentAction(action=name, rationale=rationale,  # type: ignore[arg-type]
                                 stop_reason=(state.get("current_stop_reason") if name == "stop" else None))
            next_state = action_runner(action, current, executor, limits, profile=state.get("profile"))
            if next_state == current:
                raise RuntimeError(f"Agent action {name!r} did not change State; refusing to repeat it")
            return {"agent_state": next_state}

        graph.add_node(action_name, action_node)
        graph.add_edge(action_name, "persist" if action_name == "stop" else "decide")
    graph.add_edge("persist", END)

    return graph.compile(checkpointer=checkpointer,
                         interrupt_after=list(action_names) if pause_after_action else None)


def _validated_agent_state(value: object) -> AgentState:
    return value if isinstance(value, AgentState) else AgentState.model_validate(value or {})


def _state_summary(state: AgentState) -> dict[str, object]:
    return {"round_index": state.round_index, "stop_reason": state.stop_reason,
            "candidate_sources": len(state.candidate_sources), "selected_sources": len(state.selected_sources),
            "acquired_pages": len(state.acquired_pages), "job_detail_pages": len(state.job_detail_pages),
            "prepared_jobs": len(state.prepared_jobs), "understanding_records": len(state.understanding_records),
            "match_assessments": len(state.match_assessments), "errors": len(state.errors)}
