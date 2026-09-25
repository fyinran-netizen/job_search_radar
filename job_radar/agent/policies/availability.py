"""State-driven availability policy for bounded agent actions.

This module answers whether an action has the deterministic inputs and budget
required to execute.  It does not depend on a previous action or workflow
transition table.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from job_radar.agent.action_names import AGENT_ACTION_NAMES, AgentActionName
from job_radar.agent.models import AgentLimits, AgentState, SearchOutcome
from job_radar.agent.work_manager import get_executable_count, get_pending_work
from job_radar.profile.models import UserProfile


class ActionAvailability(BaseModel):
    """Deterministic result of checking one action's hard preconditions."""

    action: AgentActionName
    available: bool
    reasons: list[str] = Field(default_factory=list)


def action_availability(
    action: AgentActionName,
    state: AgentState,
    limits: AgentLimits,
    *,
    profile: UserProfile | None = None,
) -> ActionAvailability:
    """Return hard availability without making a soft/LLM decision."""

    reasons: list[str] = []
    if action != "stop" and state.stop_reason is not None:
        reasons.append("state is already stopped")
    action_call_limit = limits.action_call_limits.get(action)
    if action_call_limit is not None:
        current = state.action_call_counts.get(action, 0)
        if current >= action_call_limit:
            reasons.append(f"action call limit reached ({current}/{action_call_limit})")

    if action == "web_search":
        if state.search_plan is None:
            reasons.append("search_plan is missing")
        if state.round_index >= limits.max_rounds:
            reasons.append("max_rounds reached")
        if state.search_plan is not None and not _plan_has_unexecuted_queries(state):
            reasons.append("all search-plan queries are already executed")
    elif action == "build_search_plan":
        if profile is None:
            reasons.append("profile is required by build_search_plan")
        if state.round_index >= limits.max_rounds:
            reasons.append("max_rounds reached")
        if state.search_plan is not None and _plan_has_unexecuted_queries(state):
            reasons.append("current search plan is still active")
        if state.last_search_outcome is SearchOutcome.ERROR:
            reasons.append("previous Tavily search failed")
        if state.last_search_outcome is SearchOutcome.STOPPED_NO_PROGRESS:
            reasons.append("no-progress stop condition reached")
    elif action == "acquire_page":
        if not state.acquisition_queue:
            reasons.append("acquisition_queue is empty")
    elif action == "analyze_page":
        if not state.acquired_pages:
            reasons.append("acquired_pages is empty")
        elif not get_pending_work(state, action):
            reasons.append("all acquired_pages are already processed")
    elif action == "job_extraction":
        if profile is None:
            reasons.append("profile is required by job_extraction")
        if not state.job_detail_pages:
            reasons.append("job_detail_pages is empty")
        elif not get_pending_work(state, action):
            reasons.append("all job_detail_pages are already extracted")
        if len(state.prepared_jobs) >= limits.max_results:
            reasons.append("max_results reached")
    elif action == "explore_followups":
        if get_executable_count(state, action) == 0:
            reasons.append("no unresolved navigation followup has a new executable href")
    elif action == "job_understanding":
        if not state.prepared_jobs:
            reasons.append("prepared_jobs is empty")
        elif not get_pending_work(state, action):
            reasons.append("all prepared_jobs are already understood")
    elif action == "match_analysis":
        if not state.understanding_records:
            reasons.append("understanding_records is empty")
        elif not get_pending_work(state, action):
            reasons.append("all understanding_records are already matched")
        if profile is None:
            reasons.append("profile is required by match_analysis")
    elif action == "stop":
        if state.stop_reason is not None:
            reasons.append("state is already stopped")
        if not _has_stop_evidence(state, limits):
            reasons.append("no deterministic stop condition is present")

    return ActionAvailability(action=action, available=not reasons, reasons=reasons)


def available_actions(
    state: AgentState,
    limits: AgentLimits,
    *,
    profile: UserProfile | None = None,
) -> list[AgentActionName]:
    """Return actions whose current-state hard preconditions are satisfied.

    Availability is derived only from the current state, limits, and profile.
    """

    return [
        name for name in AGENT_ACTION_NAMES
        if action_availability(name, state, limits, profile=profile).available
    ]


def _plan_has_unexecuted_queries(state: AgentState) -> bool:
    return bool(state.search_plan and any(q not in state.executed_queries for q in state.search_plan.queries))


def _has_stop_evidence(state: AgentState, limits: AgentLimits) -> bool:
    return (
        state.round_index >= limits.max_rounds
        or len(state.prepared_jobs) >= limits.max_results
        or state.last_search_outcome in (SearchOutcome.ERROR, SearchOutcome.STOPPED_NO_PROGRESS)
        or (not state.search_plan and not state.candidate_sources and not state.acquisition_queue)
        or (not state.acquired_pages and not state.job_detail_pages and not state.prepared_jobs and bool(state.errors))
        or (
            len(state.match_assessments) >= limits.soft_result_target
            and not any(
                get_executable_count(state, action)
                for action in (
                    "acquire_page", "analyze_page", "job_extraction",
                    "explore_followups", "job_understanding", "match_analysis",
                )
            )
        )
    )
