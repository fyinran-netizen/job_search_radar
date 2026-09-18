"""Agent v1 actions, hard preconditions, and stage handlers.

This module deliberately does not choose actions.  It provides the bounded
action vocabulary and the deterministic checks/handlers that a future
controller can call after making a decision.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

from job_radar.agent.models import AgentError, AgentLimits, AgentState, SearchOutcome
from job_radar.agent.action_names import AgentActionName
from job_radar.agent.policies.availability import action_availability, _executable_sources, _followup_excluded_urls
from job_radar.agent.transitions import stop_with_reason
from job_radar.profile.models import UserProfile
from job_radar.tools.executor import ToolExecutor
from job_radar.tools.job_extraction.tool import JobExtractionInput, JobExtractionOutput
from job_radar.tools.explore_followups.models import ExploreFollowupsInput, ExploreFollowupsOutput
from job_radar.tools.job_understanding.tool import JobUnderstandingToolInput, JobUnderstandingToolOutput
from job_radar.tools.match_analysis.tool import MatchAnalysisToolInput, MatchAnalysisToolOutput
from job_radar.tools.page_analysis.tool import PageAnalysisInput, PageAnalysisOutput
from job_radar.tools.web_search.models import CandidateSource
from job_radar.tools.search_plan import SearchPlanToolInput, SearchPlan
from job_radar.tools.web_search.source_selection import normalize_url, select_sources
from job_radar.infra.logging import get_logger

logger = get_logger(__name__)


class AgentAction(BaseModel):
    """A validated, stage-level action request.

    The action intentionally contains no source URL: collection is a batch
    stage and its handler selects executable sources from AgentState.
    """

    action: AgentActionName
    rationale: str = Field(min_length=1)
    stop_reason: str | None = None

    @model_validator(mode="after")
    def validate_stop_reason(self) -> "AgentAction":
        if self.action == "stop" and not self.stop_reason:
            raise ValueError("stop requires stop_reason")
        if self.action != "stop" and self.stop_reason is not None:
            raise ValueError("stop_reason is only valid for stop")
        return self


class ActionPreconditionError(ValueError):
    """Raised when a handler is called without its hard inputs."""


def execute_action(
    action: AgentAction,
    state: AgentState,
    executor: ToolExecutor,
    limits: AgentLimits,
    *,
    profile: UserProfile | None = None,
) -> AgentState:
    """Execute one already-selected action through existing tools.

    This is a dispatch boundary, not an LLM controller.  Each stage owns its
    batching policy; collection is currently serial by design of this handler.
    """

    availability = action_availability(action.action, state, limits, profile=profile)
    if not availability.available:
        raise ActionPreconditionError("; ".join(availability.reasons))

    state = _increment_action_call_count(state, action.action, limits)

    if action.action == "stop":
        return stop_with_reason(state, action.stop_reason or action.rationale)
    if action.action == "build_search_plan":
        return _run_build_search_plan(state, executor, limits, profile)
    if action.action == "web_search":
        return _run_web_search(state, executor, limits)
    if action.action == "acquire_page":
        return _run_acquire_page(state, executor)
    if action.action == "analyze_page":
        return _run_analyze_page(state, executor)
    if action.action == "job_extraction":
        return _run_job_extraction(state, executor, profile)
    if action.action == "explore_followups":
        return _run_explore_followups(state, executor)
    if action.action == "job_understanding":
        return _run_job_understanding(state, executor)
    return _run_match_analysis(state, executor, profile)


def _increment_action_call_count(
    state: AgentState,
    action: AgentActionName,
    limits: AgentLimits,
) -> AgentState:
    """Record one real execution for actions with configured call limits."""

    if action not in limits.action_call_limits:
        return state
    current_action_call_count = state.action_call_counts.get(action, 0)
    action_call_counts = dict(state.action_call_counts)
    action_call_counts[action] = current_action_call_count + 1
    return state.model_copy(update={"action_call_counts": action_call_counts})


def _run_web_search(state: AgentState, executor: ToolExecutor, limits: AgentLimits) -> AgentState:
    assert state.search_plan is not None
    queries = [q for q in state.search_plan.queries if q not in state.executed_queries]
    plan = state.search_plan.model_copy(update={"queries": queries})
    try:
        result = executor.run("web_search", plan)
    except Exception as exc:
        return state.model_copy(update={
            "last_search_outcome": SearchOutcome.ERROR,
            "errors": [*state.errors, AgentError(stage="web_search", reason=str(exc))],
            "executed_queries": _merge_strings(state.executed_queries, queries),
            "query_history": _merge_strings(state.query_history, queries),
        })
    if not isinstance(result, list):
        raise TypeError("web_search must return a list")
    sources = [item if isinstance(item, CandidateSource) else CandidateSource.model_validate(item) for item in result]
    previous_urls = {normalize_url(source.url) for source in state.candidate_sources}
    selected = select_sources(sources, previous_urls=previous_urls, max_sources=limits.max_sources_per_round)
    all_candidates = _merge_by_key(state.candidate_sources, sources, lambda item: normalize_url(item.url))
    logger.info(
        "search_round round_index=%s queries=%s executed_queries=%s new_urls=%s selected_sources=%s accepted_pages=%s stop_reason=%s",
        state.round_index, state.search_plan.queries, queries,
        len({normalize_url(item.url) for item in sources if normalize_url(item.url) not in previous_urls}),
        len(selected), 0, None,
    )
    return state.model_copy(update={
        "round_index": state.round_index + 1,
        "candidate_sources": all_candidates,
        "selected_sources": selected,
        "search_round_results": [*state.search_round_results, sources],
        "executed_queries": _merge_strings(state.executed_queries, queries),
        "query_history": _merge_strings(state.query_history, queries),
        "last_search_outcome": SearchOutcome.PROGRESS if selected else SearchOutcome.NO_PROGRESS,
    })


def _run_build_search_plan(state: AgentState, executor: ToolExecutor, limits: AgentLimits, profile: UserProfile | None) -> AgentState:
    assert profile is not None
    result = executor.run("build_search_plan", SearchPlanToolInput(
        profile=profile, round_index=state.round_index,
        previous_queries=state.query_history,
        previous_results=[item.model_dump() for round_items in state.search_round_results for item in round_items],
        limits={"max_queries": limits.max_queries_per_round},
    ))
    plan = result if isinstance(result, SearchPlan) else SearchPlan.model_validate(result)
    if not plan.queries:
        return state.model_copy(update={"last_search_outcome": SearchOutcome.STOPPED_NO_PROGRESS})
    return state.model_copy(update={"search_plan": plan, "executed_queries": []})


def _run_acquire_page(state: AgentState, executor: ToolExecutor) -> AgentState:
    pages = list(state.acquired_pages)
    errors = list(state.errors)
    for source in _executable_sources(state):
        try:
            page = executor.run("acquire_page", source)
            from job_radar.tools.page_acquisition.models import PageDocument
            if not isinstance(page, PageDocument):
                page = PageDocument.model_validate(page)
            pages.append(page)
        except Exception as exc:
            errors.append(AgentError(stage="acquire_page", url=source.url, title=source.title, reason=str(exc)))
    logger.info(
        "page_acquisition selected_source_count=%s accepted_page_count=%s",
        len(_executable_sources(state)), len(pages) - len(state.acquired_pages),
    )
    return state.model_copy(update={"acquired_pages": pages, "errors": errors})


def _run_analyze_page(state: AgentState, executor: ToolExecutor) -> AgentState:
    pages = _unprocessed_acquired_pages(state)
    result = executor.run("analyze_page", PageAnalysisInput(pages=pages))
    if not isinstance(result, PageAnalysisOutput):
        result = PageAnalysisOutput.model_validate(result)
    return state.model_copy(update={
        "job_detail_pages": _merge_by_key(state.job_detail_pages, result.accepted_pages, lambda page: page.url),
        "analyzed_page_urls": _merge_strings(state.analyzed_page_urls, [page.url for page in pages]),
        "pending_followups": [*state.pending_followups, *result.pending_followups],
        "rejected_pages": [*state.rejected_pages, *result.rejected_pages],
        "page_analysis_traces": _merge_by_key(state.page_analysis_traces, result.traces, lambda trace: trace.url),
        "errors": [*state.errors, *_report_errors("analyze_page", result.report)],
    })


def _run_job_extraction(state: AgentState, executor: ToolExecutor, profile: UserProfile | None) -> AgentState:
    pages = _unextracted_pages(state)
    assert profile is not None
    result = executor.run("job_extraction", JobExtractionInput(pages=pages, profile=profile))
    if not isinstance(result, JobExtractionOutput):
        result = JobExtractionOutput.model_validate(result)
    return state.model_copy(update={
        "prepared_jobs": _merge_by_key(state.prepared_jobs, result.prepared_records, lambda job: job.deduplication_key),
        "extracted_page_urls": _merge_strings(state.extracted_page_urls, [page.url for page in pages]),
        "pending_followups": [*state.pending_followups, *result.pending_followups],
        "errors": [*state.errors, *_report_errors("job_extraction", result.report)],
    })


def _run_explore_followups(state: AgentState, executor: ToolExecutor) -> AgentState:
    result = executor.run(
        "explore_followups",
        ExploreFollowupsInput(
            pending_followups=state.pending_followups,
            excluded_urls=_followup_excluded_urls(state),
            explored_links=set(state.explored_followup_links),
        ),
    )
    if not isinstance(result, ExploreFollowupsOutput):
        result = ExploreFollowupsOutput.model_validate(result)
    return state.model_copy(update={
        "candidate_sources": _merge_by_key(
            state.candidate_sources,
            result.sources,
            lambda source: normalize_url(source.url),
        ),
        "selected_sources": _merge_by_key(
            state.selected_sources,
            result.sources,
            lambda source: normalize_url(source.url),
        ),
        "explored_followup_links": _merge_strings(
            state.explored_followup_links,
            result.explored_links,
        ),
        "followup_resolutions": [
            *state.followup_resolutions,
            *[item.model_dump(mode="json") for item in result.resolutions],
        ],
    })


def _run_job_understanding(state: AgentState, executor: ToolExecutor) -> AgentState:
    jobs = _ununderstood_jobs(state)
    result = executor.run("job_understanding", JobUnderstandingToolInput(jobs=jobs))
    if not isinstance(result, JobUnderstandingToolOutput):
        result = JobUnderstandingToolOutput.model_validate(result)
    return state.model_copy(update={
        "understanding_records": _merge_by_key(state.understanding_records, result.records, lambda record: record.deduplication_key),
        "understood_job_keys": _merge_strings(state.understood_job_keys, [job.deduplication_key for job in jobs]),
        "errors": [*state.errors, *_report_errors("job_understanding", result.report)],
    })


def _run_match_analysis(state: AgentState, executor: ToolExecutor, profile: UserProfile | None) -> AgentState:
    assert profile is not None
    records = _unmatched_records(state)
    result = executor.run("match_analysis", MatchAnalysisToolInput(records=records, prepared_jobs=state.prepared_jobs, profile=profile))
    if not isinstance(result, MatchAnalysisToolOutput):
        result = MatchAnalysisToolOutput.model_validate(result)
    return state.model_copy(update={
        "match_assessments": _merge_by_key(state.match_assessments, result.assessments, lambda item: str(item.get("deduplication_key", ""))),
        "matched_job_keys": _merge_strings(state.matched_job_keys, [record.deduplication_key for record in records]),
        "errors": [*state.errors, *_report_errors("match_analysis", result.report)],
    })


def _unprocessed_acquired_pages(state: AgentState) -> list[Any]:
    completed = set(state.analyzed_page_urls)
    return [page for page in state.acquired_pages if page.url not in completed]


def _unextracted_pages(state: AgentState) -> list[Any]:
    completed = set(state.extracted_page_urls)
    return [page for page in state.job_detail_pages if page.url not in completed]


def _ununderstood_jobs(state: AgentState) -> list[Any]:
    completed = set(state.understood_job_keys)
    return [job for job in state.prepared_jobs if job.deduplication_key not in completed]


def _unmatched_records(state: AgentState) -> list[Any]:
    completed = set(state.matched_job_keys)
    return [record for record in state.understanding_records if record.deduplication_key not in completed]


def _merge_strings(existing: list[str], additions: list[str]) -> list[str]:
    return list(dict.fromkeys([*existing, *additions]))


def _merge_by_key(existing: list[Any], additions: list[Any], key) -> list[Any]:
    merged = list(existing)
    positions = {key(item): index for index, item in enumerate(merged)}
    for item in additions:
        item_key = key(item)
        if item_key in positions:
            merged[positions[item_key]] = item
        else:
            positions[item_key] = len(merged)
            merged.append(item)
    return merged


def _report_errors(stage: str, report: dict[str, Any]) -> list[AgentError]:
    raw_errors = report.get("errors", [])
    if not isinstance(raw_errors, list):
        return []
    normalized: list[AgentError] = []
    for item in raw_errors:
        if isinstance(item, dict) and "reason" in item:
            data = dict(item)
            data.setdefault("stage", stage)
            normalized.append(AgentError(**data))
        else:
            normalized.append(AgentError(stage=stage, reason=str(item)))
    return normalized
