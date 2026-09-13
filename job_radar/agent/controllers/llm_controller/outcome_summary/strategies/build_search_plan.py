"""Deterministic summary strategy for search-plan construction."""

from job_radar.agent.models import AgentState
from job_radar.infra.llm.base import AIProvider
from job_radar.agent.controllers.llm_controller.outcome_summary.common import state_queries


def summarize(
    before: AgentState,
    after: AgentState,
    provider: AIProvider | None,
    timeout_seconds: int,
) -> str:
    plan = after.search_plan

    if plan is None or not plan.queries:
        return "Search-plan construction produced no executable queries."

    parts = [f"{len(plan.queries)} executable queries"]

    if plan.target_roles:
        parts.append("target roles: " + ", ".join(plan.target_roles))

    if plan.locations:
        parts.append("locations: " + ", ".join(plan.locations))

    if plan.company_types:
        parts.append("company types: " + ", ".join(plan.company_types))

    if state_queries(before) == plan.queries:
        prefix = "Search plan was regenerated without changing the existing queries"
    else:
        prefix = "Search plan produced a new executable search direction"

    return prefix + ": " + "; ".join(parts) + "."


__all__ = ["summarize"]