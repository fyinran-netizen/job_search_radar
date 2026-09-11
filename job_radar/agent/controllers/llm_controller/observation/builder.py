"""Deterministic construction of the LLM controller observation."""

from __future__ import annotations

from job_radar.agent.controllers.base import DecisionContext
from job_radar.agent.controllers.llm_controller.observation.models import (
    CommonObservation,
    ControllerObservation,
    JobObservation,
    PageObservation,
    SearchObservation,
)
from job_radar.agent.models import AgentState
from job_radar.tools.web_search.source_selection import normalize_url


def build_observation(context: DecisionContext) -> ControllerObservation:
    """Build only the sections relevant to the supplied action namespace."""

    state = context.state
    available = set(context.available_actions)
    return ControllerObservation(
        common=CommonObservation(
            available_actions=list(context.available_actions),
            last_action=context.last_action,
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
    )


def _build_search_observation(context: DecisionContext) -> SearchObservation:
    state = context.state
    return SearchObservation(
        candidate_source_count=len(state.candidate_sources),
        selected_source_count=len(state.selected_sources),
        remaining_query_count=_remaining_queries(state),
        remaining_source_count=len(state.selected_sources) - _handled_source_count(state),
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


def _remaining_queries(state: AgentState) -> int:
    if state.search_plan is None:
        return 0
    return sum(query not in state.executed_queries for query in state.search_plan.queries)


def _handled_source_count(state: AgentState) -> int:
    handled = {normalize_url(page.url) for page in state.acquired_pages}
    handled.update(normalize_url(item.url) for item in state.pending_followups)
    handled.update(normalize_url(item.url) for item in state.rejected_pages)
    handled.update(normalize_url(error.url) for error in state.errors if error.url)
    return sum(normalize_url(source.url) in handled for source in state.selected_sources)


__all__ = ["build_observation"]
