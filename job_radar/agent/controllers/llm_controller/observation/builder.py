"""Deterministic construction of the LLM controller observation."""

from __future__ import annotations

from job_radar.agent.controllers.base import DecisionContext
from job_radar.agent.controllers.llm_controller.observation.models import (
    CommonObservation,
    ControllerObservation,
    FollowupObservation,
    JobObservation,
    PageObservation,
    SearchObservation,
)
from job_radar.agent.models import AgentState
from job_radar.tools.web_search.source_selection import normalize_url
from job_radar.tools.explore_followups.strategies.href_navigation import has_executable_href


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
        pages_to_analyze=max(0, len(state.acquired_pages) - len(state.analyzed_page_urls)),
        pages_to_extract=max(0, len(state.job_detail_pages) - len(state.extracted_page_urls)),
    )


def _build_job_observation(state: AgentState) -> JobObservation:
    return JobObservation(
        prepared_job_count=len(state.prepared_jobs),
        understanding_record_count=len(state.understanding_records),
        jobs_to_understand=max(0, len(state.prepared_jobs) - len(state.understood_job_keys)),
        records_to_match=max(0, len(state.understanding_records) - len(state.matched_job_keys)),
    )


def _build_followup_observation(state: AgentState) -> FollowupObservation:
    navigation = [
        item for item in state.pending_followups
        if item.pending_kind == "navigation_required"
    ]
    excluded = _followup_observation_excluded_urls(state)
    executable = [
        item for item in navigation
        if has_executable_href(
            [item],
            excluded_urls=excluded,
            explored_links=state.explored_followup_links,
        )
    ]
    return FollowupObservation(
        navigation_pending_count=len(navigation),
        executable_followup_count=len(executable),
        high_priority_executable_count=sum(item.priority >= 80 for item in executable),
        pre_extraction_count=sum(item.stage == "pre_extraction" for item in navigation),
        post_extraction_count=sum(item.stage == "post_extraction" for item in navigation),
    )


def _followup_observation_excluded_urls(state: AgentState) -> set[str]:
    urls = {normalize_url(page.url) for page in state.acquired_pages}
    urls.update(normalize_url(page.url) for page in state.job_detail_pages)
    urls.update(normalize_url(source.url) for source in state.acquisition_queue)
    urls.update(normalize_url(source.url) for source in state.candidate_sources)
    urls.update(normalize_url(item.url) for item in state.rejected_pages)
    urls.update(normalize_url(error.url) for error in state.errors if error.url)
    return urls


def _remaining_queries(state: AgentState) -> int:
    if state.search_plan is None:
        return 0
    return sum(query not in state.executed_queries for query in state.search_plan.queries)


def _handled_source_count(state: AgentState) -> int:
    handled = {normalize_url(page.url) for page in state.acquired_pages}
    handled.update(normalize_url(item.url) for item in state.pending_followups)
    handled.update(normalize_url(item.url) for item in state.rejected_pages)
    handled.update(normalize_url(error.url) for error in state.errors if error.url)
    return sum(normalize_url(source.url) in handled for source in state.acquisition_queue)


__all__ = ["build_observation"]
