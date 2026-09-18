"""Small deterministic baseline controller."""

from __future__ import annotations

from job_radar.agent.action_names import AgentActionName
from job_radar.agent.actions import AgentAction
from job_radar.agent.controllers.base import Controller, DecisionContext
from job_radar.agent.models import SearchOutcome


class RuleBasedController(Controller):
    """Select the next action from the current workflow state.

    This is intentionally a small baseline. It interprets state readiness
    and hard availability checks; it does not rank actions with a global
    priority list or attempt to implement agent strategy.
    """

    def decide(self, context: DecisionContext) -> AgentAction:
        state = context.state
        available = set(context.available_actions)

        if state.acquisition_queue and "acquire_page" in available:
            return self._action("acquire_page", "selected sources remain unprocessed")

        if state.acquired_pages and "analyze_page" in available:
            return self._action("analyze_page", "collected pages are ready for processing")

        if state.job_detail_pages and "job_extraction" in available:
            return self._action("job_extraction", "processed pages are ready for extraction")

        if state.prepared_jobs and "job_understanding" in available:
            if context.profile is not None:
                return self._action("job_understanding", "prepared jobs are ready for understanding")

        if state.understanding_records and "match_analysis" in available:
            if context.profile is not None:
                return self._action("match_analysis", "understanding records are ready for matching")

        if "build_search_plan" in available:
            return self._action("build_search_plan", "no current search plan exists")

        if state.search_plan is not None and "web_search" in available:
            return self._action("web_search", "search plan exists and search budget remains")

        if state.last_search_outcome is SearchOutcome.NO_PROGRESS and "build_search_plan" in available:
            return self._action("build_search_plan", "last search made no progress; re-plan")

        if "stop" in available:
            return AgentAction(
                action="stop",
                rationale="Rule-based baseline selected stop because the state satisfies a deterministic stop condition.",
                stop_reason="deterministic stop condition reached",
            )

        raise ValueError("DecisionContext has no state-supported available action")

    @staticmethod
    def _action(action: AgentActionName, state_reason: str) -> AgentAction:
        return AgentAction(
            action=action,
            rationale=f"Rule-based baseline selected {action}: {state_reason}.",
        )


__all__ = ["RuleBasedController"]
