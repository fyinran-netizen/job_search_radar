"""First model-backed workflow controller implementation."""

from __future__ import annotations

from job_radar.agent.actions import AgentAction
from job_radar.agent.action_semantics import (
    get_action_semantics,
    get_available_action_semantics,
)
from job_radar.agent.controllers.base import Controller, DecisionContext
from job_radar.agent.controllers.llm_controller.models import LLMControllerDecision
from job_radar.agent.controllers.llm_controller.observation.builder import build_observation
from job_radar.agent.controllers.llm_controller.prompt import (
    build_controller_prompt,
    build_controller_system_prompt,
)
from job_radar.infra.llm.base import AIProvider
from job_radar.infra.llm.structured_output import validate_model


class LLMController(Controller):
    """Select one action from the already policy-constrained namespace."""

    def __init__(self, provider: AIProvider, timeout_seconds: int = 60) -> None:
        self.provider = provider
        self.timeout_seconds = timeout_seconds

    def decide(self, context: DecisionContext) -> AgentAction:
        if not context.available_actions:
            raise ValueError("DecisionContext has no available actions")
        observation = build_observation(context)
        action_semantics = {}
        if context.last_action is not None:
            action_semantics[context.last_action] = get_action_semantics(context.last_action)
        action_semantics.update(get_available_action_semantics(context.available_actions))
        raw_decision = self.provider.generate_json(
            build_controller_prompt(observation, context.available_actions, action_semantics),
            timeout_seconds=self.timeout_seconds,
            system_prompt=build_controller_system_prompt(),
        )
        decision = validate_model(raw_decision, LLMControllerDecision)
        if decision.action not in context.available_actions:
            raise ValueError(
                f"LLM selected action {decision.action!r} outside available_actions"
            )
        return AgentAction(**decision.model_dump())


__all__ = ["LLMController"]
