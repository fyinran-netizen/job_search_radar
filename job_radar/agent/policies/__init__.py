"""Deterministic policies that constrain the agent action namespace."""

from job_radar.agent.policies.availability import (
    ActionAvailability,
    action_availability,
    available_actions,
)

# Kept as a descriptive compatibility alias for callers that distinguish the
# raw hard namespace from the public namespace.  They are now the same set.
hard_available_actions = available_actions

__all__ = [
    "ActionAvailability",
    "action_availability",
    "hard_available_actions",
    "available_actions",
]
