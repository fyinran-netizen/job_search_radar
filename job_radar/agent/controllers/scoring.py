"""Small, deterministic and explainable action-scoring policy."""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel, Field

from job_radar.agent.action_names import AgentActionName
from job_radar.agent.controllers.context import ActionBacklog, SchedulingContext
from job_radar.agent.controllers.features import (
    FrontierFeatures,
    GoalFeatures,
    ResultFeatures,
    SchedulingFeatures,
)


class ActionScore(BaseModel):
    """One auditable score and its additive components."""

    action: AgentActionName
    total: float
    components: dict[str, float] = Field(default_factory=dict)


# These are execution costs, not action priorities.  In particular there is
# no downstream/value ordering here: the frontier and goal signals determine
# the value of a ready action for the current state.
_COSTS: dict[AgentActionName, tuple[float, float]] = {
    "build_search_plan": (0.0, 0.5),
    "web_search": (0.0, 1.5),
    "acquire_page": (0.0, 1.0),
    "explore_followups": (0.0, 0.5),
    "analyze_page": (1.0, 0.0),
    "job_extraction": (1.0, 0.0),
    "job_understanding": (1.0, 0.0),
    "match_analysis": (1.0, 0.0),
    "stop": (0.0, 0.0),
}


def score_available_actions(
    context: SchedulingContext,
    features: SchedulingFeatures | None = None,
) -> list[ActionScore]:
    """Score every action in the current available-action space."""

    features = features or _features_from_context(context)
    return [score_action(action, features, context) for action in context.specific.available_actions]


def score_action(
    action: AgentActionName,
    features: SchedulingFeatures,
    context: SchedulingContext | None = None,
) -> ActionScore:
    """Return a transparent score for one action.

    The heuristic intentionally uses only current state, current backlog, and
    the latest observed outcome.  It has no persisted statistics or provider
    relevance metadata.
    """

    backlog = features.backlogs.get(action, ActionBacklog())
    goal = features.goal
    frontier = features.frontier
    components: dict[str, float] = {
        "backlog": min(float(backlog.executable), 10.0),
        "batch_fill": min(max(backlog.batch_fill_ratio, 0.0), 1.0) * 2.0,
        "result_deficit": _deficit_component(action, goal),
        "frontier_priority": _frontier_component(action, frontier),
        "frontier_pressure": _frontier_pressure(action, frontier),
        "expansion_value": _expansion_component(action, goal, frontier),
        "execution_cost": -_execution_cost(action),
        "recent_outcome": _recent_outcome_component(action, features),
    }
    if goal.total_match_assessments == 0 and action in {"job_extraction", "job_understanding"}:
        components["cold_start_frontier"] = 4.0
    if context and context.common.budget.refill_budget_remaining <= 0 and action in {"job_understanding", "match_analysis"}:
        components["refill_budget_pressure"] = 4.0
    if action == "stop":
        components = {"terminal_fallback": 0.0}
    if context and context.last_outcome and context.last_outcome.status in {"error", "no_progress"}:
        if action == context.last_outcome.action:
            components["repeat_penalty"] = -8.0
    return ActionScore(action=action, total=sum(components.values()), components=components)


def _deficit_component(action: AgentActionName, goal: GoalFeatures) -> float:
    deficit = float(goal.result_deficit)
    if action == "match_analysis":
        # Matching is especially valuable when only a small amount remains.
        return 12.0 if 0 < deficit <= 2 else (3.0 if deficit > 2 else 0.0)
    if action in {"job_understanding", "job_extraction", "analyze_page"}:
        return min(deficit, 8.0) * 0.75
    if action == "explore_followups":
        return min(deficit, 8.0) * 0.55
    if action == "web_search":
        # Search remains eligible to beat existing queues when the unmet goal
        # is genuinely large, but ordinary active work is not discarded for a
        # modest deficit.
        return min(deficit, 20.0) * 0.65
    if action == "build_search_plan":
        return min(deficit, 10.0) * 0.75
    return 0.0


def _frontier_component(action: AgentActionName, frontier: FrontierFeatures) -> float:
    if action != "explore_followups" or not frontier.executable_count:
        return 0.0
    priority = frontier.mean_priority or 0.0
    return priority / 10.0


def _frontier_pressure(action: AgentActionName, frontier: FrontierFeatures) -> float:
    if action != "explore_followups":
        return 0.0
    return min(float(frontier.executable_count), 6.0) * 0.75 + frontier.high_priority_executable_count * 0.5


def _expansion_component(
    action: AgentActionName,
    goal: GoalFeatures,
    frontier: FrontierFeatures,
) -> float:
    if action in {"web_search", "build_search_plan"}:
        return 0.0
    if action == "explore_followups":
        return 1.5 if frontier.executable_count else 0.0
    return 0.0


def _execution_cost(action: AgentActionName) -> float:
    llm, network = _COSTS[action]
    return llm * 1.5 + network


def _recent_outcome_component(action: AgentActionName, features: SchedulingFeatures) -> float:
    """Reward a recent positive observed yield, lightly and locally."""

    outcome = features.pipeline
    if action == "explore_followups":
        return min(float(outcome.source_enqueue_yield or 0.0), 2.0)
    if action == "job_extraction":
        return min(float(outcome.prepared_job_yield or 0.0), 2.0)
    if action == "analyze_page":
        return min(float(outcome.job_detail_yield or 0.0), 2.0)
    return 0.0


def _features_from_context(context: SchedulingContext) -> SchedulingFeatures:
    """Fallback for small unit/manual contexts that lack canonical state."""

    budget = context.common.budget
    goal = GoalFeatures(
        total_match_assessments=context.common.progress.match_result_count,
        useful_match_count=0,
        remaining_result_capacity=budget.results_remaining,
        result_deficit=max(0, budget.soft_result_target - context.common.progress.match_result_count),
        remaining_action_call_budgets=dict(budget.action_calls_remaining),
        current_step=0,
        global_steps_remaining=budget.execution_steps_remaining,
        execution_steps_remaining=budget.execution_steps_remaining,
    )
    return SchedulingFeatures(
        goal=goal,
        backlogs=dict(context.specific.backlogs),
        frontier=FrontierFeatures(),
        pipeline={},
        results=ResultFeatures(),
    )


__all__ = ["ActionScore", "score_action", "score_available_actions"]
