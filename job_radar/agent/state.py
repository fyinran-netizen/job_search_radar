"""Agent state helpers."""

from job_radar.agent.models import AgentState


def initial_agent_state() -> AgentState:
    """Create initial run state."""

    return AgentState()


