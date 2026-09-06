"""State transition helpers for agent runs."""

from job_radar.agent.models import AgentState


def stop_with_reason(state: AgentState, reason: str) -> AgentState:
    """Return a copy of state marked as stopped."""

    return state.model_copy(update={"stop_reason": reason})


