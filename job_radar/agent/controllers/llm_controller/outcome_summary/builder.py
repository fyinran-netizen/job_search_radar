"""Unified entry point and action dispatch for outcome summaries."""

from __future__ import annotations

from collections.abc import Callable

from job_radar.agent.action_names import AgentActionName
from job_radar.agent.models import AgentState
from job_radar.infra.llm.base import AIProvider
from job_radar.agent.controllers.llm_controller.outcome_summary import strategies


Strategy = Callable[[AgentState, AgentState, AIProvider | None, int], str]


class ActionOutcomeSummarizer:
    """Dispatch completed action transitions to their dedicated strategies."""

    def __init__(self, provider: AIProvider | None = None, timeout_seconds: int = 60) -> None:
        self.provider = provider
        self.timeout_seconds = timeout_seconds

    def summarize(self, action: AgentActionName, before_state: AgentState, after_state: AgentState) -> str:
        return strategies.STRATEGIES[action](before_state, after_state, self.provider, self.timeout_seconds)


__all__ = ["ActionOutcomeSummarizer"]
