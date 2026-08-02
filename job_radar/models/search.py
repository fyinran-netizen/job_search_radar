"""Search-related data contracts."""

from pydantic import BaseModel, Field


class SearchPlan(BaseModel):
    """Search strategy generated from a user profile."""

    target_roles: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    company_types: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)


class CandidateSource(BaseModel):
    """A candidate URL returned by a search tool."""

    url: str
    title: str
    source_name: str
    company_name: str | None = None
    company_type: str | None = None
    is_official: bool = False
    relevance_score: int = 0
    reason: str = ""
