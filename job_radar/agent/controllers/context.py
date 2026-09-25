"""Small, structured input used by the deterministic scheduler."""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field

from job_radar.agent.action_names import AgentActionName
from job_radar.agent.models import AgentLimits, AgentState
from job_radar.agent.work_manager import get_action_batch_size, get_executable_count, get_pending_count


class ActionBacklog(BaseModel):
    pending: int = 0
    executable: int = 0
    batch_size: int = 0
    batch_fill_ratio: float = 0.0


class SchedulerBudget(BaseModel):
    rounds_remaining: int
    results_remaining: int
    soft_result_target: int
    soft_scope_reached: bool
    round_result_target: int = 3
    round_match_result_count: int = 0
    round_steps_remaining: int = 999
    refill_budget_remaining: int = 2
    action_calls_remaining: dict[AgentActionName, int] = Field(default_factory=dict)


class OverallProgress(BaseModel):
    """Small set of cross-action progress metrics used by scheduling."""

    match_result_count: int = 0


class CommonContext(BaseModel):
    """Information shared by every scheduling decision."""

    budget: SchedulerBudget
    progress: OverallProgress


class SpecificContext(BaseModel):
    """Signals for the currently available action space only."""

    available_actions: list[AgentActionName]
    backlogs: dict[AgentActionName, ActionBacklog] = Field(default_factory=dict)
    search_plan_active: bool | None = None
    search_queries_remaining: int | None = None


class BuildSearchPlanOutcome(BaseModel):
    kind: Literal["build_search_plan"] = "build_search_plan"
    queries_created: int
    plan_created: bool


class WebSearchOutcome(BaseModel):
    kind: Literal["web_search"] = "web_search"
    queries_executed: int
    raw_results: int
    sources_added: int
    sources_enqueued: int


class AcquirePageOutcome(BaseModel):
    kind: Literal["acquire_page"] = "acquire_page"
    attempted: int
    acquired: int
    failed: int
    queue_remaining: int


class AnalyzePageOutcome(BaseModel):
    kind: Literal["analyze_page"] = "analyze_page"
    pages_analyzed: int
    job_detail_pages_added: int
    followups_added: int
    rejected_pages_added: int


class JobExtractionOutcome(BaseModel):
    kind: Literal["job_extraction"] = "job_extraction"
    pages_extracted: int
    prepared_jobs_added: int
    pending_followups_added: int


class ExploreFollowupsOutcome(BaseModel):
    kind: Literal["explore_followups"] = "explore_followups"
    followups_processed: int
    links_explored: int
    sources_enqueued: int
    resolutions: dict[str, int] = Field(default_factory=dict)


class JobUnderstandingOutcome(BaseModel):
    kind: Literal["job_understanding"] = "job_understanding"
    jobs_processed: int
    records_added: int


class MatchAnalysisOutcome(BaseModel):
    kind: Literal["match_analysis"] = "match_analysis"
    records_processed: int
    assessments_added: int


class StopOutcome(BaseModel):
    kind: Literal["stop"] = "stop"
    stop_reason: str


ActionOutcomePayload = Annotated[
    Union[
        BuildSearchPlanOutcome, WebSearchOutcome, AcquirePageOutcome,
        AnalyzePageOutcome, JobExtractionOutcome, ExploreFollowupsOutcome,
        JobUnderstandingOutcome, MatchAnalysisOutcome, StopOutcome,
    ],
    Field(discriminator="kind"),
]


class ExecutionMetrics(BaseModel):
    elapsed_ms: float = 0.0
    llm_calls: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class LastActionOutcome(BaseModel):
    """Common envelope around one action's deterministic outcome payload."""

    action: AgentActionName
    status: Literal["progress", "partial", "no_progress", "error", "stopped"]
    state_changed: bool
    errors_added: int = 0
    signals: list[str] = Field(default_factory=list)
    execution: ExecutionMetrics = Field(default_factory=ExecutionMetrics)
    payload: ActionOutcomePayload


class SchedulingContext(BaseModel):
    """Bounded scheduler input; it intentionally is not an AgentState copy."""

    common: CommonContext
    specific: SpecificContext
    last_outcome: LastActionOutcome | None = None


def build_scheduling_context(
    state: AgentState,
    limits: AgentLimits,
    available_actions: list[AgentActionName],
    *,
    last_outcome: LastActionOutcome | None = None,
) -> SchedulingContext:
    """Project run state into the three scheduler-specific context layers."""
    batched_actions = (
        "acquire_page", "analyze_page", "job_extraction", "explore_followups",
        "job_understanding", "match_analysis",
    )
    available_set = set(available_actions)
    backlogs = {
        action: ActionBacklog(
            pending=get_pending_count(state, action),
            executable=get_executable_count(state, action),
            batch_size=get_action_batch_size(limits, action) or 0,
        )
        for action in batched_actions
        if action in available_set
    }
    for backlog in backlogs.values():
        backlog.batch_fill_ratio = (
            backlog.executable / backlog.batch_size
            if backlog.batch_size > 0
            else 0.0
        )
    search_relevant = available_set & {"build_search_plan", "web_search"}
    remaining_queries = (
        sum(query not in state.executed_queries for query in state.search_plan.queries)
        if state.search_plan else 0
    )
    return SchedulingContext(
        common=CommonContext(
            budget=SchedulerBudget(
                rounds_remaining=max(0, limits.max_rounds - state.round_index),
                results_remaining=max(0, limits.max_results - len(state.prepared_jobs)),
                soft_result_target=limits.soft_result_target,
                soft_scope_reached=len(state.match_assessments) >= limits.soft_result_target,
                round_result_target=limits.round_result_target,
                round_match_result_count=state.round_match_result_count,
                round_steps_remaining=max(0, limits.round_step_budget - state.round_step_count),
                refill_budget_remaining=max(0, limits.refill_budget - state.round_refill_count),
                action_calls_remaining={
                    action: max(0, limit - state.action_call_counts.get(action, 0))
                    for action, limit in limits.action_call_limits.items()
                },
            ),
            progress=OverallProgress(match_result_count=len(state.match_assessments)),
        ),
        specific=SpecificContext(
            available_actions=available_actions,
            backlogs=backlogs,
            search_plan_active=(remaining_queries > 0 if search_relevant else None),
            search_queries_remaining=(remaining_queries if search_relevant else None),
        ),
        last_outcome=last_outcome,
    )


__all__ = [
    "ActionBacklog", "ActionOutcomePayload", "AcquirePageOutcome", "AnalyzePageOutcome",
    "BuildSearchPlanOutcome", "CommonContext", "ExploreFollowupsOutcome",
    "JobExtractionOutcome", "JobUnderstandingOutcome", "LastActionOutcome",
    "ExecutionMetrics", "MatchAnalysisOutcome", "OverallProgress", "SchedulerBudget",
    "StopOutcome", "SpecificContext", "SchedulingContext", "WebSearchOutcome",
    "build_scheduling_context",
]
