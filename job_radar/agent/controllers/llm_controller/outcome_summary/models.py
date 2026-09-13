"""Structured output model for one completed action's semantic outcome."""

from pydantic import BaseModel, Field


class ActionSemanticSummary(BaseModel):
    """Short controller-facing meaning of an action's state transition."""

    summary: str = Field(min_length=1, max_length=600)


__all__ = ["ActionSemanticSummary"]
