"""Deterministic summary strategy for workflow termination."""

from job_radar.agent.models import AgentState
from job_radar.infra.llm.base import AIProvider


def summarize(before: AgentState, after: AgentState, provider: AIProvider | None, timeout_seconds: int) -> str:
    return f"The workflow reached a terminal decision: {after.stop_reason or 'no stop reason recorded'}."


__all__ = ["summarize"]
