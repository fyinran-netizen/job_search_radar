"""Run-state and run-result models for agent workflows."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from job_radar.profile.models import ProfileCompletenessResult
from job_radar.tools.job_extraction.models import AIPageInput, JobRecord
from job_radar.tools.job_understanding.models import JobUnderstandingRecord
from job_radar.tools.page_acquisition.models import PageDocument, RejectedPage, ToolEvent
from job_radar.tools.page_analysis.models import PendingFollowup
from job_radar.tools.web_search.models import CandidateSource, SearchPlan


class AgentLimits(BaseModel):
    """Small, explicit limits that keep agent runs bounded."""

    max_rounds: int = Field(
        default=3,
        ge=1,
        description="Maximum number of search rounds in one run.",
    )
    max_sources_per_round: int = Field(
        default=10,
        ge=1,
        description="Maximum candidate pages selected for collection per round.",
    )
    min_relevance_score: int = Field(
        default=70,
        ge=0,
        le=100,
        description="Minimum source relevance score accepted for collection.",
    )
    max_results: int = Field(
        default=20,
        ge=1,
        description="Maximum accumulated job results retained for a run.",
    )
    max_steps: int = Field(default=25, ge=1)
    max_queries_per_round: int = Field(default=6, ge=1)


class AgentError(BaseModel):
    """A structured, non-fatal error that can inform later workflow actions."""

    model_config = ConfigDict(extra="allow")

    stage: str = "unknown"
    reason: str
    index: int | None = None
    url: str | None = None
    title: str | None = None
    company_name: str | None = None
    deduplication_key: str | None = None
    source_name: str | None = None


class AgentState(BaseModel):
    """Validated data carried between actions in one agent workflow."""

    round_index: int = 0
    stop_reason: str | None = None
    notices: list[str] = Field(default_factory=list)

    search_plan: SearchPlan | None = None
    query_history: list[str] = Field(default_factory=list)
    executed_queries: list[str] = Field(default_factory=list)
    search_round_results: list[list[CandidateSource]] = Field(default_factory=list)
    last_search_outcome: str | None = None
    candidate_sources: list[CandidateSource] = Field(default_factory=list)
    selected_sources: list[CandidateSource] = Field(default_factory=list)

    acquired_pages: list[PageDocument] = Field(default_factory=list)
    job_detail_pages: list[AIPageInput] = Field(default_factory=list)
    # Stage completion is tracked separately from output presence.  A stage
    # may legitimately produce no output (for example, a page with no job),
    # so downstream lists cannot be used as completion markers.
    analyzed_page_urls: list[str] = Field(default_factory=list)
    extracted_page_urls: list[str] = Field(default_factory=list)
    pending_followups: list[PendingFollowup] = Field(default_factory=list)
    rejected_pages: list[RejectedPage] = Field(default_factory=list)

    prepared_jobs: list[JobRecord] = Field(default_factory=list)
    understanding_records: list[JobUnderstandingRecord] = Field(default_factory=list)
    understood_job_keys: list[str] = Field(default_factory=list)
    match_assessments: list[dict[str, Any]] = Field(default_factory=list)
    matched_job_keys: list[str] = Field(default_factory=list)
    errors: list[AgentError] = Field(default_factory=list)


class AgentRunResult(BaseModel):
    """Trace and summary from a job discovery agent run."""

    run_id: str | None = None
    profile_check: ProfileCompletenessResult
    search_plan: SearchPlan | None = None
    search_plan_source: str = "deterministic"
    search_plan_error: str | None = None
    candidate_sources: list[CandidateSource] = Field(default_factory=list)
    selected_sources: list[CandidateSource] = Field(default_factory=list)
    acquired_pages_count: int = 0
    extracted_count: int = 0
    tool_events: list[ToolEvent] = Field(default_factory=list)
    errors: list[AgentError] = Field(default_factory=list)
