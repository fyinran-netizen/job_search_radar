"""Structured decisions and run summaries for agent workflows."""

from pydantic import BaseModel, Field

from job_radar.models.search import CandidateSource, SearchPlan
from job_radar.models.tool import ToolEvent


class ProfileCompletenessResult(BaseModel):
    """Result of checking whether a user profile is usable for search."""

    is_complete: bool
    missing_fields: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)


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
