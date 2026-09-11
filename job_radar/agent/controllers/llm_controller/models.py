"""Structured model returned by the LLM workflow controller."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from job_radar.agent.action_names import AgentActionName


class LLMControllerDecision(BaseModel):
    """Minimal structured response expected from the controller model."""

    action: AgentActionName
    rationale: str = Field(min_length=1)
    stop_reason: str | None = None

    @model_validator(mode="after")
    def validate_stop_reason(self) -> "LLMControllerDecision":
        if self.action == "stop" and not self.stop_reason:
            raise ValueError("stop requires stop_reason")
        if self.action != "stop" and self.stop_reason is not None:
            raise ValueError("stop_reason is only valid for stop")
        return self


__all__ = ["LLMControllerDecision"]
