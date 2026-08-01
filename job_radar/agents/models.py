"""Structured inputs and outputs for the agent layer."""

from typing import Any

from pydantic import BaseModel, Field


class ProfileCompletenessResult(BaseModel):
    """Result of checking whether a user profile is usable for search."""

    is_complete: bool
    missing_fields: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)


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


class PageContent(BaseModel):
    """Fetched page content returned by a page collection tool."""

    url: str
    source_name: str
    title: str
    text: str
    html: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolEvent(BaseModel):
    """One executed tool call."""

    tool_name: str
    input_summary: str
    output_summary: str


class AgentRunResult(BaseModel):
    """Trace and summary from a job discovery agent run."""

    profile_check: ProfileCompletenessResult
    search_plan: SearchPlan | None = None
    candidate_sources: list[CandidateSource] = Field(default_factory=list)
    selected_sources: list[CandidateSource] = Field(default_factory=list)
    collected_pages_count: int = 0
    extracted_count: int = 0
    tool_events: list[ToolEvent] = Field(default_factory=list)
    errors: list[dict[str, str]] = Field(default_factory=list)
