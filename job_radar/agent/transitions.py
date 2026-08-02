"""State transition helpers for agent runs."""

from job_radar.models.run import AgentState


def advance_round(state: AgentState) -> AgentState:
    """Return a copy of state advanced by one search round."""

    return state.model_copy(update={"round_index": state.round_index + 1})


def stop_with_reason(state: AgentState, reason: str) -> AgentState:
    """Return a copy of state marked as stopped."""

    return state.model_copy(update={"stop_reason": reason})
