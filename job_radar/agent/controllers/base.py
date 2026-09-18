"""Shared controller contract and decision context."""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel, Field

from job_radar.agent.actions import AgentAction
from job_radar.agent.action_names import AgentActionName
from job_radar.agent.models import AgentLimits, AgentState
from job_radar.profile.models import UserProfile


class DecisionContext(BaseModel):
    """Validated inputs supplied to a controller for one decision."""

    state: AgentState
    limits: AgentLimits = Field(default_factory=AgentLimits)
    profile: UserProfile | None = None
    available_actions: list[AgentActionName] = Field(default_factory=list)
    stage: AgentActionName | None = None
    last_action: AgentActionName | None = None

class Controller(ABC):
    """Common interface implemented by every agent controller."""

    @abstractmethod
    def decide(self, context: DecisionContext) -> AgentAction:
        """Choose the next bounded action from a decision context."""

__all__ = ["Controller", "DecisionContext"]
