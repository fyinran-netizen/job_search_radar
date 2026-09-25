"""Deterministic action outcomes derived from action state transitions."""

from __future__ import annotations

from collections import Counter
from typing import Literal

from job_radar.agent.action_names import AgentActionName
from job_radar.agent.controllers.context import (
    AcquirePageOutcome,
    AnalyzePageOutcome,
    BuildSearchPlanOutcome,
    ExecutionMetrics,
    ExploreFollowupsOutcome,
    JobExtractionOutcome,
    JobUnderstandingOutcome,
    LastActionOutcome,
    MatchAnalysisOutcome,
    StopOutcome,
    WebSearchOutcome,
)
from job_radar.agent.models import AgentState, SearchOutcome


Status = Literal["progress", "partial", "no_progress", "error", "stopped"]


def build_outcome(
    action: AgentActionName,
    before: AgentState,
    after: AgentState,
    *,
    execution: ExecutionMetrics | None = None,
) -> LastActionOutcome:
    """Build the smallest useful outcome available from the state delta."""

    errors_added = max(0, len(after.errors) - len(before.errors))
    payload, meaningful, signals = _payload(action, before, after)
    if action == "stop":
        status: Status = "stopped"
    elif errors_added and meaningful:
        status = "partial"
    elif errors_added:
        status = "error"
    elif meaningful:
        status = "progress"
    else:
        status = "no_progress"
    return LastActionOutcome(
        action=action,
        status=status,
        state_changed=after != before,
        errors_added=errors_added,
        signals=signals,
        execution=execution or ExecutionMetrics(),
        payload=payload,
    )


def _payload(action: AgentActionName, before: AgentState, after: AgentState):
    if action == "build_search_plan":
        plan_created = after.search_plan is not None and after.search_plan != before.search_plan
        queries = len(after.search_plan.queries) if after.search_plan else 0
        return BuildSearchPlanOutcome(queries_created=queries, plan_created=plan_created), queries > 0, _plan_signals(after, queries)

    if action == "web_search":
        queries = len(set(after.executed_queries) - set(before.executed_queries))
        raw_results = max(0, len(after.search_round_results[-1]) if len(after.search_round_results) > len(before.search_round_results) else 0)
        sources_added = max(0, len(after.candidate_sources) - len(before.candidate_sources))
        enqueued = max(0, len(after.acquisition_queue) - len(before.acquisition_queue))
        meaningful = after.last_search_outcome is SearchOutcome.PROGRESS and enqueued > 0
        signals = [after.last_search_outcome.value] if after.last_search_outcome else []
        if enqueued:
            signals.append("new_acquisition_work")
        return WebSearchOutcome(queries_executed=queries, raw_results=raw_results,
                                sources_added=sources_added, sources_enqueued=enqueued), meaningful, signals

    if action == "acquire_page":
        attempted = max(0, len(before.acquisition_queue) - len(after.acquisition_queue))
        acquired = max(0, len(after.acquired_pages) - len(before.acquired_pages))
        failed = max(0, len(after.errors) - len(before.errors))
        meaningful = acquired > 0
        signals = ["page_acquired"] if acquired else []
        if failed and acquired:
            signals.append("partial_acquisition")
        if failed and not acquired:
            signals.append("all_failed")
        return AcquirePageOutcome(attempted=attempted, acquired=acquired, failed=failed,
                                  queue_remaining=len(after.acquisition_queue)), meaningful, signals

    if action == "analyze_page":
        analyzed = max(0, len(after.analyzed_page_urls) - len(before.analyzed_page_urls))
        details = max(0, len(after.job_detail_pages) - len(before.job_detail_pages))
        followups = max(0, len(after.pending_followups) - len(before.pending_followups))
        rejected = max(0, len(after.rejected_pages) - len(before.rejected_pages))
        signals = []
        if details:
            signals.append("job_detail_found")
        if followups:
            signals.append("followup_required")
        if rejected:
            signals.append("page_rejected")
        return AnalyzePageOutcome(pages_analyzed=analyzed, job_detail_pages_added=details,
                                  followups_added=followups, rejected_pages_added=rejected), bool(details or followups or rejected), signals

    if action == "job_extraction":
        pages = max(0, len(after.extracted_page_urls) - len(before.extracted_page_urls))
        jobs = max(0, len(after.prepared_jobs) - len(before.prepared_jobs))
        followups = max(0, len(after.pending_followups) - len(before.pending_followups))
        signals = []
        if jobs:
            signals.append("jobs_prepared")
        if followups:
            signals.append("pending_followup_created")
        return JobExtractionOutcome(pages_extracted=pages, prepared_jobs_added=jobs,
                                    pending_followups_added=followups), bool(jobs or followups), signals

    if action == "explore_followups":
        processed = max(0, len(after.processed_followup_urls) - len(before.processed_followup_urls))
        links = max(0, len(after.explored_followup_links) - len(before.explored_followup_links))
        sources = max(0, len(after.acquisition_queue) - len(before.acquisition_queue))
        resolutions = Counter(
            item.get("status") for item in after.followup_resolutions[len(before.followup_resolutions):]
            if item.get("status")
        )
        signals = ["new_sources_discovered"] if sources else []
        return ExploreFollowupsOutcome(followups_processed=processed, links_explored=links,
                                       sources_enqueued=sources, resolutions=dict(resolutions)), sources > 0, signals

    if action == "job_understanding":
        jobs = max(0, len(after.understood_job_keys) - len(before.understood_job_keys))
        records = max(0, len(after.understanding_records) - len(before.understanding_records))
        return JobUnderstandingOutcome(jobs_processed=jobs, records_added=records), records > 0, ["understanding_created"] if records else []

    if action == "match_analysis":
        records = max(0, len(after.matched_job_keys) - len(before.matched_job_keys))
        assessments = max(0, len(after.match_assessments) - len(before.match_assessments))
        return MatchAnalysisOutcome(records_processed=records, assessments_added=assessments), assessments > 0, ["assessment_created"] if assessments else []

    return StopOutcome(stop_reason=after.stop_reason or "unknown"), False, ["terminal"]


def _plan_signals(state: AgentState, queries: int) -> list[str]:
    if queries:
        return ["plan_created"]
    if state.last_search_outcome is SearchOutcome.STOPPED_NO_PROGRESS:
        return ["plan_empty", "stopped_no_progress"]
    return ["plan_empty"]


__all__ = ["build_outcome"]
