"""Deterministic outcome summary for follow-up exploration."""

from job_radar.agent.models import AgentState


def summarize(before: AgentState, after: AgentState, provider, timeout_seconds: int) -> str:
    del provider, timeout_seconds
    new_sources = len(after.candidate_sources) - len(before.candidate_sources)
    explored = len(after.explored_followup_links) - len(before.explored_followup_links)
    return (
        f"Follow-up exploration found {new_sources} new source(s) from "
        f"{explored} explicit href target(s)."
    )
