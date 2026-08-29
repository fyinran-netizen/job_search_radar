"""Reserved controller boundary for a future structured LLM implementation."""

from __future__ import annotations

from job_radar.agent.actions import AgentAction
from job_radar.agent.controllers.base import Controller, DecisionContext


class LLMController(Controller):
    """Placeholder with the same contract as the deterministic controller."""

    def decide(self, context: DecisionContext) -> AgentAction:
        raise NotImplementedError(
            "LLMController is reserved for a future validated model-backed implementation; "
            "no model, prompt, or API is connected yet."
        )


__all__ = ["LLMController"]
