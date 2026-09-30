"""Derived, deterministic scheduling features.

This module is deliberately a projection of runtime state.  It does not add
policy decisions to ``AgentState`` and it does not treat search-provider
metadata as observed quality evidence.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from pydantic import BaseModel, Field

from job_radar.agent.action_names import AgentActionName
from job_radar.agent.controllers.context import (
    ActionBacklog,
    ExecutionMetrics,
    LastActionOutcome,
    SchedulingContext,
)
from job_radar.agent.models import AgentLimits, AgentState
from job_radar.agent.work_manager import (
    BATCHED_ACTIONS,
    get_action_batch_size,
    get_executable_count,
    get_pending_count,
    is_followup_executable,
)


class GoalFeatures(BaseModel):
    total_match_assessments: int = 0
    useful_match_count: int = 0
    remaining_result_capacity: int = 0
    result_deficit: int = 0
    remaining_action_call_budgets: dict[AgentActionName, int] = Field(default_factory=dict)
    current_step: int = 0
    global_steps_remaining: int = 0
    execution_steps_remaining: int = 0


class FrontierFeatures(BaseModel):
    pending_count: int = 0
    executable_count: int = 0
    counts_by_pending_kind: dict[str, int] = Field(default_factory=dict)
    counts_by_suggested_next_action: dict[str, int] = Field(default_factory=dict)
    counts_by_stage: dict[str, int] = Field(default_factory=dict)
    priority_distribution: dict[str, int] = Field(default_factory=dict)
    mean_priority: float | None = None
    max_priority: int | None = None
    high_priority_executable_count: int = 0
    usable_link_count: int = 0
    official_count: int = 0
    non_official_count: int = 0
    semantic_type_counts: dict[str, int] = Field(default_factory=dict)
    semantic_confidence_counts: dict[str, int] = Field(default_factory=dict)


class PipelineOutcomeFeatures(BaseModel):
    acquisition_attempted: int = 0
    acquisition_acquired: int = 0
    acquisition_failed: int = 0
    acquisition_queue_remaining: int = 0
    acquisition_success_ratio: float | None = None

    pages_analyzed: int = 0
    job_detail_pages_produced: int = 0
    analysis_followups_produced: int = 0
    rejected_pages: int = 0
    job_detail_yield: float | None = None
    rejection_ratio: float | None = None

    followups_processed: int = 0
    links_explored: int = 0
    new_sources_enqueued: int = 0
    resolution_counts: dict[str, int] = Field(default_factory=dict)
    source_enqueue_yield: float | None = None

    extraction_pages_processed: int = 0
    prepared_jobs_produced: int = 0
    extraction_pending_followups_produced: int = 0
    prepared_job_yield: float | None = None

    understanding_jobs_processed: int = 0
    understanding_records_produced: int = 0
    match_records_processed: int = 0
    assessments_produced: int = 0


class ResultFeatures(BaseModel):
    recommendation_counts: dict[str, int] = Field(default_factory=dict)
    apply_count: int = 0
    consider_count: int = 0
    low_priority_count: int = 0
    skip_count: int = 0
    average_match_score: float | None = None
    risk_flagged_count: int = 0
    missing_requirement_count: int = 0


class CostFeatures(BaseModel):
    elapsed_ms: float = 0.0
    llm_calls: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class SchedulingFeatures(BaseModel):
    goal: GoalFeatures
    backlogs: dict[AgentActionName, ActionBacklog] = Field(default_factory=dict)
    frontier: FrontierFeatures
    pipeline: PipelineOutcomeFeatures
    results: ResultFeatures
    recent_execution: CostFeatures | None = None


def build_scheduling_features(
    state: AgentState,
    limits: AgentLimits,
    context: SchedulingContext,
    last_outcome: LastActionOutcome | None = None,
) -> SchedulingFeatures:
    """Build deterministic policy-facing signals from canonical state."""

    outcome = last_outcome or context.last_outcome
    return SchedulingFeatures(
        goal=_goal_features(state, limits, context),
        backlogs=_backlogs(state, limits),
        frontier=_frontier_features(state),
        pipeline=_pipeline_features(state, outcome),
        results=_result_features(state.match_assessments),
        recent_execution=CostFeatures.model_validate(outcome.execution.model_dump()) if outcome else None,
    )


def _goal_features(state: AgentState, limits: AgentLimits, context: SchedulingContext) -> GoalFeatures:
    total = len(state.match_assessments)
    useful = sum(
        _assessment_value(item, "recommendation") in {"apply", "consider"}
        for item in state.match_assessments
    )
    return GoalFeatures(
        total_match_assessments=total,
        useful_match_count=useful,
        remaining_result_capacity=max(0, limits.max_results - len(state.prepared_jobs)),
        result_deficit=max(0, limits.soft_result_target - total),
        remaining_action_call_budgets=dict(context.common.budget.action_calls_remaining),
        current_step=state.execution_step_count,
        global_steps_remaining=max(0, limits.max_steps - state.execution_step_count),
        execution_steps_remaining=context.common.budget.execution_steps_remaining,
    )


def _backlogs(state: AgentState, limits: AgentLimits) -> dict[AgentActionName, ActionBacklog]:
    result: dict[AgentActionName, ActionBacklog] = {}
    for action in BATCHED_ACTIONS:
        batch_size = get_action_batch_size(limits, action) or 0
        executable = get_executable_count(state, action)
        result[action] = ActionBacklog(
            pending=get_pending_count(state, action),
            executable=executable,
            batch_size=batch_size,
            batch_fill_ratio=executable / batch_size if batch_size else 0.0,
        )
    return result


def _frontier_features(state: AgentState) -> FrontierFeatures:
    items = state.pending_followups
    priorities = [item.priority for item in items]
    executable = [item for item in items if is_followup_executable(state, item)]
    semantic_types = Counter(
        str(item.evidence.get("page_type") or item.evidence.get("semantic_type"))
        for item in items
        if item.evidence.get("page_type") or item.evidence.get("semantic_type")
    )
    confidences = Counter(
        str(item.evidence.get("confidence"))
        for item in items
        if item.evidence.get("confidence")
    )
    return FrontierFeatures(
        pending_count=len(items),
        executable_count=len(executable),
        counts_by_pending_kind=dict(Counter(item.pending_kind for item in items)),
        counts_by_suggested_next_action=dict(Counter(item.suggested_next_action for item in items)),
        counts_by_stage=dict(Counter(item.stage for item in items)),
        priority_distribution=dict(Counter(str(item.priority) for item in items)),
        mean_priority=sum(priorities) / len(priorities) if priorities else None,
        max_priority=max(priorities) if priorities else None,
        high_priority_executable_count=sum(item.priority >= 75 for item in executable),
        usable_link_count=sum(_usable_link_count(item) for item in items),
        official_count=sum(item.is_official for item in items),
        non_official_count=sum(not item.is_official for item in items),
        semantic_type_counts=dict(semantic_types),
        semantic_confidence_counts=dict(confidences),
    )


def _pipeline_features(state: AgentState, outcome: LastActionOutcome | None) -> PipelineOutcomeFeatures:
    values: dict[str, Any] = {
        "acquisition_attempted": 0,
        "acquisition_failed": 0,
        "acquisition_acquired": len(state.acquired_pages),
        "acquisition_queue_remaining": len(state.acquisition_queue),
        "pages_analyzed": len(state.analyzed_page_urls),
        "job_detail_pages_produced": len(state.job_detail_pages),
        "analysis_followups_produced": sum(1 for item in state.pending_followups if item.stage == "pre_extraction"),
        "rejected_pages": len(state.rejected_pages),
        "followups_processed": len(state.processed_followup_urls),
        "links_explored": len(state.explored_followup_links),
        "new_sources_enqueued": len(state.selected_sources),
        "resolution_counts": dict(Counter(item.get("status") for item in state.followup_resolutions if item.get("status"))),
        "extraction_pages_processed": len(state.extracted_page_urls),
        "prepared_jobs_produced": len(state.prepared_jobs),
        "extraction_pending_followups_produced": sum(1 for item in state.pending_followups if item.stage == "post_extraction"),
        "understanding_jobs_processed": len(state.understood_job_keys),
        "understanding_records_produced": len(state.understanding_records),
        "match_records_processed": len(state.matched_job_keys),
        "assessments_produced": len(state.match_assessments),
    }
    if outcome:
        payload = outcome.payload
        if payload.kind == "acquire_page":
            values.update(acquisition_attempted=payload.attempted, acquisition_acquired=payload.acquired,
                          acquisition_failed=payload.failed, acquisition_queue_remaining=payload.queue_remaining)
        elif payload.kind == "analyze_page":
            values.update(pages_analyzed=payload.pages_analyzed, job_detail_pages_produced=payload.job_detail_pages_added,
                          analysis_followups_produced=payload.followups_added, rejected_pages=payload.rejected_pages_added)
        elif payload.kind == "explore_followups":
            values.update(followups_processed=payload.followups_processed, links_explored=payload.links_explored,
                          new_sources_enqueued=payload.sources_enqueued, resolution_counts=payload.resolutions)
        elif payload.kind == "job_extraction":
            values.update(extraction_pages_processed=payload.pages_extracted, prepared_jobs_produced=payload.prepared_jobs_added,
                          extraction_pending_followups_produced=payload.pending_followups_added)
        elif payload.kind == "job_understanding":
            values.update(understanding_jobs_processed=payload.jobs_processed, understanding_records_produced=payload.records_added)
        elif payload.kind == "match_analysis":
            values.update(match_records_processed=payload.records_processed, assessments_produced=payload.assessments_added)
    attempted = values["acquisition_attempted"]
    analyzed = values["pages_analyzed"]
    links = values["links_explored"]
    values["acquisition_success_ratio"] = values["acquisition_acquired"] / attempted if attempted else None
    values["job_detail_yield"] = values["job_detail_pages_produced"] / analyzed if analyzed else None
    values["rejection_ratio"] = values["rejected_pages"] / analyzed if analyzed else None
    values["source_enqueue_yield"] = values["new_sources_enqueued"] / links if links else None
    extracted = values["extraction_pages_processed"]
    values["prepared_job_yield"] = values["prepared_jobs_produced"] / extracted if extracted else None
    return PipelineOutcomeFeatures(**values)


def _result_features(assessments: list[dict[str, Any]]) -> ResultFeatures:
    recommendations = Counter(
        recommendation
        for item in assessments
        if (recommendation := _assessment_value(item, "recommendation")) is not None
    )
    scores = [_assessment_value(item, "match_score") for item in assessments]
    scores = [score for score in scores if isinstance(score, (int, float))]
    return ResultFeatures(
        recommendation_counts=dict(recommendations),
        apply_count=recommendations.get("apply", 0),
        consider_count=recommendations.get("consider", 0),
        low_priority_count=recommendations.get("low_priority", 0),
        skip_count=recommendations.get("skip", 0),
        average_match_score=sum(scores) / len(scores) if scores else None,
        risk_flagged_count=sum(bool(_assessment_value(item, "risk_flags")) for item in assessments),
        missing_requirement_count=sum(bool(_assessment_value(item, "missing_requirements")) for item in assessments),
    )


def _assessment_value(item: dict[str, Any], key: str) -> Any:
    assessment = item.get("assessment") if isinstance(item, dict) else None
    source = assessment if isinstance(assessment, dict) else item
    return source.get(key) if isinstance(source, dict) else None


def _usable_link_count(item: Any) -> int:
    return sum(bool(link.get("href") or link.get("url")) for link in item.links if isinstance(link, dict))


__all__ = ["CostFeatures", "FrontierFeatures", "GoalFeatures", "PipelineOutcomeFeatures", "ResultFeatures", "SchedulingFeatures", "build_scheduling_features"]
