"""Run-state models for orchestrated agent workflows."""

from pydantic import BaseModel, Field


class AgentLimits(BaseModel):
    """Limits that keep local agent runs bounded."""

    max_rounds: int = 1
    max_sources_per_round: int = 10
    min_relevance_score: int = 70


class AgentState(BaseModel):
    """Minimal state carried by an agent run."""

    round_index: int = 0
    stop_reason: str | None = None
    notices: list[str] = Field(default_factory=list)
