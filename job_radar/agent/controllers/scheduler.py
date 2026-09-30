"""Deterministic, explainable dynamic action scheduler."""

from __future__ import annotations

from dataclasses import dataclass

from job_radar.agent.actions import AgentAction
from job_radar.agent.action_names import AgentActionName
from job_radar.agent.controllers.context import SchedulingContext
from job_radar.agent.controllers.features import SchedulingFeatures
from job_radar.agent.controllers.scoring import ActionScore, score_available_actions


@dataclass(frozen=True)
class ActionProfile:
    """Static execution characteristics used as cost signals only."""

    uses_llm: bool
    uses_network: bool


ACTION_PROFILES: dict[AgentActionName, ActionProfile] = {
    "build_search_plan": ActionProfile(uses_llm=False, uses_network=False),
    "web_search": ActionProfile(uses_llm=False, uses_network=True),
    "acquire_page": ActionProfile(uses_llm=False, uses_network=True),
    "explore_followups": ActionProfile(uses_llm=False, uses_network=False),
    "analyze_page": ActionProfile(uses_llm=True, uses_network=False),
    "job_extraction": ActionProfile(uses_llm=True, uses_network=False),
    "job_understanding": ActionProfile(uses_llm=True, uses_network=False),
    "match_analysis": ActionProfile(uses_llm=True, uses_network=False),
    "stop": ActionProfile(uses_llm=False, uses_network=False),
}

_TIE_ORDER: tuple[AgentActionName, ...] = (
    "match_analysis", "job_understanding", "job_extraction", "analyze_page",
    "explore_followups", "acquire_page", "web_search", "build_search_plan", "stop",
)


def schedule(
    context: SchedulingContext,
    features: SchedulingFeatures | None = None,
) -> AgentAction:
    """Select the highest-scoring currently executable action."""

    action, _ = schedule_with_scores(context, features)
    return action


def schedule_with_scores(
    context: SchedulingContext,
    features: SchedulingFeatures | None = None,
) -> tuple[AgentAction, list[ActionScore]]:
    """Return the scheduled action and the complete decision trace scores."""

    scores = score_available_actions(context, features)
    available = set(context.specific.available_actions)

    if context.common.budget.results_remaining <= 0 and "stop" in available:
        return _stop("hard result cap reached", "max_results"), scores

    if (
        context.common.budget.soft_scope_reached
        and context.last_outcome
        and context.last_outcome.status == "error"
        and "stop" in available
    ):
        return _stop("soft result target reached after an action error", "no_progress"), scores

    productive = {
        action for action, backlog in context.specific.backlogs.items()
        if action in available and backlog.executable > 0
    }
    search = {
        action for action in available
        if action == "web_search"
        and context.common.budget.search_rounds_remaining > 0
        and not context.common.budget.soft_scope_reached
    }
    if not productive and "build_search_plan" in available and context.common.budget.search_rounds_remaining > 0:
        search.add("build_search_plan")
    candidates = productive | search

    if not candidates:
        if "stop" in available:
            if context.last_outcome and context.last_outcome.status == "error":
                return _stop("the previous action failed and no productive path remains", "no_progress"), scores
            reason = (
                "soft result target reached and no valuable existing work remains"
                if context.common.budget.soft_scope_reached
                else "no executable work or viable search path remains"
            )
            return _stop(reason, "frontier_exhausted" if context.common.budget.soft_scope_reached else "no_progress"), scores
        raise ValueError("SchedulingContext has no available action")

    score_by_action = {item.action: item for item in scores}
    chosen = max(
        candidates,
        key=lambda action: (
            score_by_action[action].total,
            -_TIE_ORDER.index(action),
        ),
    )
    chosen_score = score_by_action[chosen]
    rationale = _rationale(context, chosen, chosen_score, candidates, score_by_action)
    return AgentAction(action=chosen, rationale=rationale), scores


def _rationale(
    context: SchedulingContext,
    chosen: AgentActionName,
    score: ActionScore,
    candidates: set[AgentActionName],
    score_by_action: dict[AgentActionName, ActionScore],
) -> str:
    components = ", ".join(
        f"{name}={value:g}" for name, value in score.components.items() if value
    ) or "no positive components"
    rationale = f"dynamic score {score.total:g} ({components})"
    if context.last_outcome and chosen != context.last_outcome.action:
        rationale += f"; switched away from previous {context.last_outcome.action} {context.last_outcome.status}"
    if chosen == "job_extraction" and "explore_followups" in candidates:
        rationale += "; downstream extraction work has the stronger current score"
    if chosen == "analyze_page" and "job_extraction" in candidates:
        rationale += "; holding partial downstream batch(es) while upstream work is available"
    if len(candidates) > 1:
        alternatives = ", ".join(
            f"{action}={score_by_action[action].total:g}"
            for action in sorted(candidates)
            if action != chosen
        )
        if alternatives:
            rationale += f"; alternatives: {alternatives}"
    return f"Deterministic scheduler selected {chosen}: {rationale}."


def _stop(reason: str, stop_reason: str) -> AgentAction:
    return AgentAction(
        action="stop",
        rationale=f"Deterministic scheduler selected stop: {reason}.",
        stop_reason=stop_reason,
    )


__all__ = ["ACTION_PROFILES", "ActionProfile", "schedule", "schedule_with_scores"]
