"""Deterministic, explainable action scheduling policy."""

from __future__ import annotations

from dataclasses import dataclass

from job_radar.agent.actions import AgentAction
from job_radar.agent.action_names import AgentActionName
from job_radar.agent.controllers.context import SchedulingContext


@dataclass(frozen=True)
class ActionProfile:
    """Static execution characteristics used only for close decisions."""

    value_group: int
    uses_llm: bool
    uses_network: bool


ACTION_PROFILES: dict[AgentActionName, ActionProfile] = {
    "build_search_plan": ActionProfile(value_group=0, uses_llm=False, uses_network=False),
    "web_search": ActionProfile(value_group=0, uses_llm=False, uses_network=True),
    "acquire_page": ActionProfile(value_group=1, uses_llm=False, uses_network=True),
    "explore_followups": ActionProfile(value_group=1, uses_llm=False, uses_network=False),
    "analyze_page": ActionProfile(value_group=2, uses_llm=True, uses_network=False),
    "job_extraction": ActionProfile(value_group=2, uses_llm=True, uses_network=False),
    "job_understanding": ActionProfile(value_group=3, uses_llm=True, uses_network=False),
    "match_analysis": ActionProfile(value_group=4, uses_llm=True, uses_network=False),
    "stop": ActionProfile(value_group=-1, uses_llm=False, uses_network=False),
}

_STABLE_TIE_ORDER: tuple[AgentActionName, ...] = (
    "match_analysis", "job_understanding", "job_extraction", "analyze_page",
    "explore_followups", "acquire_page", "web_search", "build_search_plan", "stop",
)

# These are structural dependencies, not a fixed execution order.  They are
# used only by the small-batch hold rule to identify cheaper work that can
# still feed a partially full downstream batch.
_UPSTREAM_ACTION: dict[AgentActionName, AgentActionName] = {
    "analyze_page": "acquire_page",
    "job_extraction": "analyze_page",
    "job_understanding": "job_extraction",
    "match_analysis": "job_understanding",
}


def schedule(context: SchedulingContext) -> AgentAction:
    """Select an action using backlog, outcome, budget, and soft-scope signals."""

    available = set(context.specific.available_actions)
    if context.common.budget.rounds_remaining <= 0 and "stop" in available:
        return _stop("maximum processing rounds reached", "max_rounds")

    productive = _productive_actions(context, available)
    deferred_retry: AgentActionName | None = None
    if productive:
        selected = _select_productive(context, productive)
        if selected is not None:
            action, reason = selected
            return _action(action, reason)
        if context.last_outcome and context.last_outcome.action in productive:
            deferred_retry = context.last_outcome.action

    if _soft_scope_can_close(context, available):
        return _stop(
            "soft result target reached and no valuable existing work remains",
            "frontier_exhausted",
        )

    search_action = _select_search_action(context, available)
    if search_action is not None:
        return search_action

    if "stop" in available:
        if context.last_outcome and context.last_outcome.status == "error":
            return _stop("the previous action failed and no productive path remains", "no_progress")
        return _stop("no executable work or viable search path remains", _terminal_stop_reason(context))
    if deferred_retry is not None:
        return _action(
            deferred_retry,
            f"all alternative productive and fallback paths are unavailable; retrying {deferred_retry}",
        )
    raise ValueError("SchedulingContext has no available action")


def _productive_actions(context: SchedulingContext, available: set[AgentActionName]) -> list[AgentActionName]:
    return [
        action for action in available
        if action in context.specific.backlogs
        and context.specific.backlogs[action].executable > 0
    ]


def _select_productive(
    context: SchedulingContext,
    productive: list[AgentActionName],
) -> tuple[AgentActionName, str] | None:
    outcome = context.last_outcome
    candidates = list(productive)
    if outcome and outcome.status in {"no_progress", "error"} and outcome.action in candidates:
        alternatives = [action for action in candidates if action != outcome.action]
        if alternatives:
            candidates = alternatives
        else:
            # Defer the same action until soft-close, search/replan, and stop
            # fallbacks have had a chance to handle the boundary.
            return None

    held = _held_productive_actions(context, candidates)
    if held and len(held) < len(candidates):
        candidates = [action for action in candidates if action not in held]

    continuation = set(_continuation_candidates(outcome, candidates))
    chosen = _best_productive(context, candidates, continuation)
    if chosen in continuation and outcome is not None:
        return chosen, f"the previous {outcome.action} actually produced {chosen} downstream work; this is a frontier preference"

    backlog = context.specific.backlogs[chosen]
    reason = f"{backlog.executable} executable {chosen} item(s) remain"
    if held:
        held_names = ", ".join(sorted(held))
        reason += f"; holding partial downstream batch(es) {held_names} while upstream work is available"
    if continuation:
        reason += "; a previous downstream result was considered as a preference"
    if outcome and outcome.status in {"no_progress", "error"} and chosen != outcome.action:
        reason += f"; switched away from previous {outcome.action} {outcome.status}"
    return chosen, reason


def _continuation_candidates(outcome, candidates: list[AgentActionName]) -> list[AgentActionName]:
    if outcome is None or outcome.status not in {"progress", "partial"}:
        return []
    payload = outcome.payload
    opened: list[AgentActionName] = []
    if payload.kind == "build_search_plan" and payload.queries_created > 0:
        opened.append("web_search")
    elif payload.kind == "web_search" and payload.sources_enqueued > 0:
        opened.append("acquire_page")
    elif payload.kind == "acquire_page" and payload.acquired > 0:
        opened.append("analyze_page")
    elif payload.kind == "analyze_page":
        if payload.job_detail_pages_added > 0:
            opened.append("job_extraction")
        if payload.followups_added > 0:
            opened.append("explore_followups")
    elif payload.kind == "job_extraction":
        if payload.prepared_jobs_added > 0:
            opened.append("job_understanding")
        if payload.pending_followups_added > 0:
            opened.append("explore_followups")
    elif payload.kind == "explore_followups" and payload.sources_enqueued > 0:
        opened.append("acquire_page")
    elif payload.kind == "job_understanding" and payload.records_added > 0:
        opened.append("match_analysis")
    return [action for action in opened if action in candidates]


def _held_productive_actions(
    context: SchedulingContext,
    candidates: list[AgentActionName],
) -> set[AgentActionName]:
    """Return partial downstream LLM batches that can safely wait briefly."""

    budget = context.common.budget
    if (
        context.common.progress.match_result_count == 0
        or budget.refill_budget_remaining <= 0
        or budget.round_steps_remaining <= 1
    ):
        return set()

    held: set[AgentActionName] = set()
    candidate_set = set(candidates)
    for action in candidates:
        profile = ACTION_PROFILES[action]
        backlog = context.specific.backlogs[action]
        if not profile.uses_llm or _batch_fill_ratio(backlog) >= 1.0:
            continue
        upstream = _UPSTREAM_ACTION.get(action)
        if upstream not in candidate_set:
            continue
        upstream_profile = ACTION_PROFILES[upstream]
        upstream_backlog = context.specific.backlogs[upstream]
        # Equal-cost upstream work is useful too when its fuller batch makes
        # the comparison materially better.  This covers LLM-to-LLM stages.
        upstream_is_no_more_expensive = (
            int(upstream_profile.uses_llm), int(upstream_profile.uses_network)
        ) <= (
            int(profile.uses_llm), int(profile.uses_network)
        )
        if upstream_is_no_more_expensive and _batch_fill_ratio(upstream_backlog) >= _batch_fill_ratio(backlog):
            held.add(action)
    return held


def _batch_fill_ratio(backlog) -> float:
    """Read the explicit context signal, with a safe manual-context fallback."""

    if backlog.batch_fill_ratio > 0:
        return backlog.batch_fill_ratio
    if backlog.batch_size > 0:
        return backlog.executable / backlog.batch_size
    return 0.0


def _best_productive(
    context: SchedulingContext,
    candidates: list[AgentActionName],
    continuation: set[AgentActionName] | None = None,
) -> AgentActionName:
    """Choose by coarse value, batch readiness, then light cost tie-breaks."""

    continuation = continuation or set()
    match_count = context.common.progress.match_result_count

    return max(
        candidates,
        key=lambda action: (
            ACTION_PROFILES[action].value_group,
            # Before the first result, keep the closest downstream stage
            # moving.  Once results exist, fuller batches improve frontier
            # utilization within the same value group.
            (
                -_STABLE_TIE_ORDER.index(action)
                if match_count == 0
                else _batch_fill_ratio(context.specific.backlogs[action])
            ),
            context.specific.backlogs[action].executable,
            int(action in continuation),
            -int(ACTION_PROFILES[action].uses_llm),
            -int(ACTION_PROFILES[action].uses_network),
            -_STABLE_TIE_ORDER.index(action),
        ),
    )


def _select_search_action(
    context: SchedulingContext,
    available: set[AgentActionName],
) -> AgentAction | None:
    budget = context.common.budget
    if budget.rounds_remaining <= 0 or budget.soft_scope_reached:
        return None
    soft_note = ""
    if "web_search" in available and context.specific.search_plan_active:
        remaining = context.specific.search_queries_remaining or 0
        reason = f"{remaining} planned quer{'y' if remaining == 1 else 'ies'} remain and existing work is exhausted{soft_note}"
        if context.last_outcome and context.last_outcome.status in {"no_progress", "error"}:
            reason += f"; no alternative productive path exists after previous {context.last_outcome.action} {context.last_outcome.status}"
        return _action("web_search", reason)
    if "build_search_plan" in available:
        reason = f"no active search plan remains and existing work is exhausted{soft_note}"
        if context.last_outcome and context.last_outcome.status in {"no_progress", "error"}:
            reason += f"; switching to replanning after previous {context.last_outcome.action} {context.last_outcome.status}"
        return _action("build_search_plan", reason)
    return None


def _terminal_stop_reason(context: SchedulingContext) -> str:
    """Map bounded scheduler context to a stable terminal reason."""

    budget = context.common.budget
    if budget.rounds_remaining <= 0:
        return "max_rounds"
    if budget.results_remaining <= 0:
        return "max_results"
    return "frontier_exhausted"


def _soft_scope_can_close(context: SchedulingContext, available: set[AgentActionName]) -> bool:
    return context.common.budget.soft_scope_reached and "stop" in available


def _action(action: AgentActionName, reason: str) -> AgentAction:
    return AgentAction(action=action, rationale=f"Deterministic scheduler selected {action}: {reason}.")


def _stop(reason: str, stop_reason: str = "deterministic scheduler found no remaining work") -> AgentAction:
    return AgentAction(action="stop", rationale=f"Deterministic scheduler selected stop: {reason}.", stop_reason=stop_reason)


__all__ = ["ACTION_PROFILES", "ActionProfile", "schedule"]
