"""Agent v1 actions, hard preconditions, and stage handlers.

This module deliberately does not choose actions.  It provides the bounded
action vocabulary and the deterministic checks/handlers that a future
controller can call after making a decision.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from job_radar.agent.guardrails import select_candidate_sources
from job_radar.agent.models import AgentError, AgentLimits, AgentState
from job_radar.agent.transitions import stop_with_reason
from job_radar.profile.models import UserProfile
from job_radar.tools.executor import ToolExecutor
from job_radar.tools.job_extraction.tool import JobExtractionInput, JobExtractionOutput
from job_radar.tools.job_understanding.tool import JobUnderstandingToolInput, JobUnderstandingToolOutput
from job_radar.tools.match_analysis.tool import MatchAnalysisToolInput, MatchAnalysisToolOutput
from job_radar.tools.page_processing.tool import PageProcessingInput, PageProcessingOutput
from job_radar.tools.web_search.models import CandidateSource


AgentActionName = Literal[
    "web_search",
    "collect_page",
    "page_processing",
    "job_extraction",
    "job_understanding",
    "match_analysis",
    "stop",
]


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


class ActionAvailability(BaseModel):
    """Deterministic result of checking one action's hard preconditions."""

    action: AgentActionName
    available: bool
    reasons: list[str] = Field(default_factory=list)


class ActionPreconditionError(ValueError):
    """Raised when a handler is called without its hard inputs."""


def action_availability(
    action: AgentActionName,
    state: AgentState,
    limits: AgentLimits,
    *,
    profile: UserProfile | None = None,
) -> ActionAvailability:
    """Return availability without making any soft/LLM decision."""

    reasons: list[str] = []
    if action != "stop" and state.stop_reason is not None:
        reasons.append("state is already stopped")

    if action == "web_search":
        if state.search_plan is None:
            reasons.append("search_plan is missing")
        if state.round_index >= limits.max_rounds:
            reasons.append("max_rounds reached")
        if len(state.prepared_jobs) >= limits.max_results:
            reasons.append("max_results reached")
    elif action == "collect_page":
        if not state.selected_sources:
            reasons.append("selected_sources is empty")
        if not _executable_sources(state):
            reasons.append("no unprocessed executable selected_sources")
        if len(state.prepared_jobs) >= limits.max_results:
            reasons.append("max_results reached")
    elif action == "page_processing":
        if not state.collected_pages:
            reasons.append("collected_pages is empty")
        elif not _unprocessed_collected_pages(state):
            reasons.append("all collected_pages are already processed")
    elif action == "job_extraction":
        if not state.processed_pages:
            reasons.append("processed_pages is empty")
        elif not _unextracted_pages(state):
            reasons.append("all processed_pages are already extracted")
        if len(state.prepared_jobs) >= limits.max_results:
            reasons.append("max_results reached")
    elif action == "job_understanding":
        if not state.prepared_jobs:
            reasons.append("prepared_jobs is empty")
        elif not _ununderstood_jobs(state):
            reasons.append("all prepared_jobs are already understood")
        if profile is None:
            reasons.append("profile is required by job_understanding")
    elif action == "match_analysis":
        if not state.understanding_records:
            reasons.append("understanding_records is empty")
        elif not _unmatched_records(state):
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
    """List actions passing hard checks; this does not rank or choose them."""

    names: tuple[AgentActionName, ...] = (
        "web_search", "collect_page", "page_processing", "job_extraction",
        "job_understanding", "match_analysis", "stop",
    )
    return [name for name in names if action_availability(name, state, limits, profile=profile).available]


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

    if action.action == "stop":
        return stop_with_reason(state, action.stop_reason or action.rationale)
    if action.action == "web_search":
        return _run_web_search(state, executor, limits)
    if action.action == "collect_page":
        return _run_collect_page(state, executor)
    if action.action == "page_processing":
        return _run_page_processing(state, executor)
    if action.action == "job_extraction":
        return _run_job_extraction(state, executor)
    if action.action == "job_understanding":
        return _run_job_understanding(state, executor, profile)
    return _run_match_analysis(state, executor, profile)


def _run_web_search(state: AgentState, executor: ToolExecutor, limits: AgentLimits) -> AgentState:
    result = executor.run("web_search", state.search_plan)
    if not isinstance(result, list):
        raise TypeError("web_search must return a list")
    sources = [item if isinstance(item, CandidateSource) else CandidateSource.model_validate(item) for item in result]
    selected = select_candidate_sources(sources, limits.min_relevance_score)[: limits.max_sources_per_round]
    return state.model_copy(update={
        "round_index": state.round_index + 1,
        "candidate_sources": sources,
        "selected_sources": selected,
    })


def _run_collect_page(state: AgentState, executor: ToolExecutor) -> AgentState:
    pages = list(state.collected_pages)
    errors = list(state.errors)
    for source in _executable_sources(state):
        try:
            page = executor.run("collect_page", source)
            from job_radar.tools.page_collection.models import PageContent
            if not isinstance(page, PageContent):
                page = PageContent.model_validate(page)
            pages.append(page)
        except Exception as exc:
            errors.append(AgentError(stage="collect_page", url=source.url, title=source.title, reason=str(exc)))
    return state.model_copy(update={"collected_pages": pages, "errors": errors})


def _run_page_processing(state: AgentState, executor: ToolExecutor) -> AgentState:
    pages = _unprocessed_collected_pages(state)
    result = executor.run("page_processing", PageProcessingInput(pages=pages, search_plan=state.search_plan))
    if not isinstance(result, PageProcessingOutput):
        result = PageProcessingOutput.model_validate(result)
    return state.model_copy(update={
        "processed_pages": _merge_by_key(state.processed_pages, result.accepted_pages, lambda page: page.url),
        "processed_page_urls": _merge_strings(state.processed_page_urls, [page.url for page in pages]),
        "pending_followups": [*state.pending_followups, *result.pending_followups],
        "rejected_pages": [*state.rejected_pages, *result.rejected_pages],
        "errors": [*state.errors, *_report_errors("page_processing", result.report)],
    })


def _run_job_extraction(state: AgentState, executor: ToolExecutor) -> AgentState:
    pages = _unextracted_pages(state)
    result = executor.run("job_extraction", JobExtractionInput(pages=pages))
    if not isinstance(result, JobExtractionOutput):
        result = JobExtractionOutput.model_validate(result)
    return state.model_copy(update={
        "prepared_jobs": _merge_by_key(state.prepared_jobs, result.prepared_records, lambda job: job.deduplication_key),
        "extracted_page_urls": _merge_strings(state.extracted_page_urls, [page.url for page in pages]),
        "pending_followups": [*state.pending_followups, *result.pending_followups],
        "errors": [*state.errors, *_report_errors("job_extraction", result.report)],
    })


def _run_job_understanding(state: AgentState, executor: ToolExecutor, profile: UserProfile | None) -> AgentState:
    assert profile is not None
    jobs = _ununderstood_jobs(state)
    result = executor.run("job_understanding", JobUnderstandingToolInput(jobs=jobs, profile=profile))
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
    result = executor.run("match_analysis", MatchAnalysisToolInput(records=records, profile=profile))
    if not isinstance(result, MatchAnalysisToolOutput):
        result = MatchAnalysisToolOutput.model_validate(result)
    return state.model_copy(update={
        "match_assessments": _merge_by_key(state.match_assessments, result.assessments, lambda item: str(item.get("deduplication_key", ""))),
        "matched_job_keys": _merge_strings(state.matched_job_keys, [record.deduplication_key for record in records]),
        "errors": [*state.errors, *_report_errors("match_analysis", result.report)],
    })


def _executable_sources(state: AgentState) -> list[CandidateSource]:
    handled = _state_urls(state)
    return [source for source in state.selected_sources if source.url not in handled]


def _state_urls(state: AgentState) -> set[str]:
    urls = {page.url for page in state.collected_pages}
    urls.update(item.url for item in state.pending_followups)
    urls.update(item.url for item in state.rejected_pages)
    urls.update(error.url for error in state.errors if error.url)
    return urls


def _unprocessed_collected_pages(state: AgentState) -> list[Any]:
    completed = set(state.processed_page_urls)
    return [page for page in state.collected_pages if page.url not in completed]


def _unextracted_pages(state: AgentState) -> list[Any]:
    completed = set(state.extracted_page_urls)
    return [page for page in state.processed_pages if page.url not in completed]


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


def _has_stop_evidence(state: AgentState, limits: AgentLimits) -> bool:
    return (
        state.round_index >= limits.max_rounds
        or len(state.prepared_jobs) >= limits.max_results
        or (not state.search_plan and not state.candidate_sources and not state.selected_sources)
        or (not state.collected_pages and not state.processed_pages and not state.prepared_jobs and bool(state.errors))
    )


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
