"""Search review boundary for future bounded continuation decisions."""

from job_radar.agent.models import AgentState


def should_continue_search(state: AgentState, max_rounds: int) -> bool:
    """Return whether another search round is allowed by current limits."""

    return state.stop_reason is None and state.round_index < max_rounds
