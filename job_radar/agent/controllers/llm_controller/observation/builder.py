"""Deterministic construction of the LLM controller observation."""

from __future__ import annotations

from job_radar.agent.controllers.base import DecisionContext
from job_radar.agent.controllers.llm_controller.observation.models import (
    ActionBacklogObservation,
    CommonObservation,
    ControllerObservation,
    FollowupObservation,
    JobObservation,
    PageObservation,
    SearchObservation,
)
from job_radar.agent.work_manager import (
    BATCHED_ACTIONS,
    get_action_batch_size,
    get_executable_count,
    is_followup_executable,
    get_pending_count,
)
from job_radar.agent.models import AgentState
def build_observation(context: DecisionContext) -> ControllerObservation:
    """Build only the sections relevant to the supplied action namespace."""

    state = context.state
    available = set(context.available_actions)
    return ControllerObservation(
        common=CommonObservation(
            available_actions=list(context.available_actions),
            last_action=context.last_action,
            last_action_summary=state.last_action_summary,
            stage=context.stage,
            round_index=state.round_index,
            max_rounds=context.limits.max_rounds,
            profile_present=context.profile is not None,
            status=state.stop_reason or (
                state.last_search_outcome.value if state.last_search_outcome else "active"
            ),
            remaining_action_call_budget={
                action: max(0, limit - state.action_call_counts.get(action, 0))
                for action, limit in context.limits.action_call_limits.items()
            },
        ),
        search=_build_search_observation(context) if available & {"build_search_plan", "web_search"} else None,
        pages=_build_page_observation(state) if available & {"acquire_page", "analyze_page", "job_extraction"} else None,
        jobs=_build_job_observation(state) if available & {"job_understanding", "match_analysis"} else None,
        followups=_build_followup_observation(state),
        backlogs={
            action: ActionBacklogObservation(
                pending_count=get_pending_count(state, action),
                executable_count=get_executable_count(state, action),
                batch_size=get_action_batch_size(context.limits, action) or 0,
                available=action in available,
            )
            for action in BATCHED_ACTIONS
        },
    )


def _build_search_observation(context: DecisionContext) -> SearchObservation:
    state = context.state
    return SearchObservation(
        candidate_source_count=len(state.candidate_sources),
        selected_source_count=len(state.acquisition_queue),
        remaining_query_count=_remaining_queries(state),
        remaining_source_count=len(state.acquisition_queue),
        last_search_outcome=state.last_search_outcome.value if state.last_search_outcome else None,
    )


def _build_page_observation(state: AgentState) -> PageObservation:
    return PageObservation(
        acquired_page_count=len(state.acquired_pages),
        job_detail_page_count=len(state.job_detail_pages),
        pages_to_analyze=get_pending_count(state, "analyze_page"),
        pages_to_extract=get_pending_count(state, "job_extraction"),
    )


def _build_job_observation(state: AgentState) -> JobObservation:
    return JobObservation(
        prepared_job_count=len(state.prepared_jobs),
        understanding_record_count=len(state.understanding_records),
        jobs_to_understand=get_pending_count(state, "job_understanding"),
        records_to_match=get_pending_count(state, "match_analysis"),
    )


def _build_followup_observation(state: AgentState) -> FollowupObservation:
    navigation = [
        item for item in state.pending_followups
        if item.pending_kind == "navigation_required"
    ]
    executable = [
        item for item in navigation
        if is_followup_executable(state, item)
    ]
    return FollowupObservation(
        navigation_pending_count=len(navigation),
        executable_followup_count=len(executable),
        high_priority_executable_count=sum(item.priority >= 80 for item in executable),
        pre_extraction_count=sum(item.stage == "pre_extraction" for item in navigation),
        post_extraction_count=sum(item.stage == "post_extraction" for item in navigation),
    )


def _remaining_queries(state: AgentState) -> int:
    if state.search_plan is None:
        return 0
    return sum(query not in state.executed_queries for query in state.search_plan.queries)


__all__ = ["build_observation"]
