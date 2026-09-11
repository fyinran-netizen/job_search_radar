"""Composition of deterministic policy namespaces."""

from __future__ import annotations

from job_radar.agent.action_names import AgentActionName
from job_radar.agent.models import AgentLimits, AgentState
from job_radar.agent.policies.availability import available_actions as hard_available_actions
from job_radar.agent.policies.transition import transition_allowed_actions
from job_radar.profile.models import UserProfile


def available_actions(
    state: AgentState,
    limits: AgentLimits,
    *,
    profile: UserProfile | None = None,
    last_action: AgentActionName | None = None,
    stage: str | None = None,
) -> list[AgentActionName]:
    """Return the final namespace allowed by both deterministic policies."""

    hard = hard_available_actions(state, limits, profile=profile)
    allowed = set(transition_allowed_actions(last_action, stage=stage))
    return [name for name in hard if name in allowed]


__all__ = ["available_actions"]
