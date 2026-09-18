"""Canonical vocabulary for actions supported by the agent graph."""

from typing import Final, Literal


AgentActionName = Literal[
    "build_search_plan",
    "web_search",
    "acquire_page",
    "analyze_page",
    "job_extraction",
    "explore_followups",
    "job_understanding",
    "match_analysis",
    "stop",
]

AGENT_ACTION_NAMES: Final[tuple[AgentActionName, ...]] = (
    "build_search_plan",
    "web_search",
    "acquire_page",
    "analyze_page",
    "job_extraction",
    "explore_followups",
    "job_understanding",
    "match_analysis",
    "stop",
)
