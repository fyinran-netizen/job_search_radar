"""Search-related data contracts."""

from pydantic import BaseModel, Field


class SearchPlan(BaseModel):
    """Search strategy generated from a user profile."""

    target_roles: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    company_types: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    cohort_year: int | None = None
    graduation_start: str | None = None
    graduation_end: str | None = None
    cohort_terms: list[str] = Field(default_factory=list)


class CandidateSource(BaseModel):
    """A candidate URL returned by a search tool."""

    url: str
    title: str
    source_name: str
    company_name: str | None = None
    company_type: str | None = None
    location: str | None = None
    is_official: bool = False
    relevance_score: int = 0
    reason: str = ""
