"""Workflow transition policy, independent of state/input availability."""

from __future__ import annotations

from job_radar.agent.action_names import AGENT_ACTION_NAMES, AgentActionName


_TRANSITIONS: dict[AgentActionName, tuple[AgentActionName, ...]] = {
    "build_search_plan": ("web_search", "stop"),
    "web_search": ("acquire_page", "build_search_plan", "stop"),
    "acquire_page": ("analyze_page", "stop"),
    "analyze_page": ("analyze_page", "job_extraction", "stop"),
    "job_extraction": ("job_understanding", "stop"),
    "job_understanding": ("job_understanding", "match_analysis", "stop"),
    "match_analysis": ("match_analysis", "build_search_plan", "stop"),
    "stop": (),
}


def transition_allowed_actions(
    last_action: AgentActionName | None = None,
    *,
    stage: str | None = None,
) -> list[AgentActionName]:
    """Return the namespace allowed by workflow position alone.

    With no position supplied (for example, the initial decision), all
    canonical actions remain structurally possible.  ``stage`` is accepted as
    a boundary-friendly alias for callers that track stage separately.
    """

    current = last_action or (stage if stage in _TRANSITIONS else None)
    if current is None:
        return list(AGENT_ACTION_NAMES)
    return list(_TRANSITIONS[current])


__all__ = ["transition_allowed_actions"]
