"""Run-state and run-result models for agent workflows."""

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from job_radar.agent.action_names import AgentActionName
from job_radar.profile.models import ProfileCompletenessResult
from job_radar.tools.job_extraction.models import JobRecord
from job_radar.tools.job_understanding.models import JobUnderstandingRecord
from job_radar.tools.page_acquisition.models import PageDocument, RejectedPage, ToolEvent
from job_radar.tools.page_analysis.models import AIPageInput, PageAnalysisTrace, PendingFollowup
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
    # 暂时保留，当前不执行 relevance score 阈值过滤，后续如有需要再启用。
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
    soft_result_target: int = Field(
        default=8,
        ge=1,
        description="Soft target for useful match results; not a hard stop.",
    )
    round_result_target: int = Field(
        default=3,
        ge=1,
        description="Incremental match-result target for yielding to the next search round.",
    )
    round_step_budget: int = Field(
        default=8,
        ge=1,
        description="Maximum scheduler actions processed within one search round.",
    )
    refill_budget: int = Field(
        default=2,
        ge=0,
        description="Maximum upstream refill actions allowed for partial LLM batches per round.",
    )
    max_steps: int = Field(default=25, ge=1)
    acquire_batch_size: int = Field(default=3, ge=1)
    analyze_batch_size: int = Field(default=3, ge=1)
    extraction_batch_size: int = Field(default=3, ge=1)
    understanding_batch_size: int = Field(default=3, ge=1)
    match_batch_size: int = Field(default=3, ge=1)
    followup_batch_size: int = Field(default=3, ge=1)
    max_queries_per_round: int = Field(default=6, ge=1)
    action_call_limits: dict[AgentActionName, int] = Field(
        default_factory=lambda: {
            "build_search_plan": 3,
            "analyze_page": 3,
            "job_extraction": 3,
            "explore_followups": 3,
            "job_understanding": 3,
            "match_analysis": 3,
        }
    )


class SearchOutcome(str, Enum):
    """Outcome of the latest search or search-planning operation."""

    PROGRESS = "progress"
    NO_PROGRESS = "no_progress"
    ERROR = "error"
    STOPPED_NO_PROGRESS = "stopped_no_progress"


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
    round_step_count: int = 0
    round_match_result_count: int = 0
    round_refill_count: int = 0
    round_end_reason: str | None = None
    stop_reason: str | None = None
    action_call_counts: dict[AgentActionName, int] = Field(default_factory=dict)

    search_plan: SearchPlan | None = None
    query_history: list[str] = Field(default_factory=list)
    executed_queries: list[str] = Field(default_factory=list)
    search_round_results: list[list[CandidateSource]] = Field(default_factory=list)   # 暂时保留：后续考虑替换为更轻量的 search_round_summaries。
    last_search_outcome: SearchOutcome | None = None
    candidate_sources: list[CandidateSource] = Field(default_factory=list)
    acquisition_queue: list[CandidateSource] = Field(default_factory=list)
    # Deprecated compatibility/debugging history. Acquisition execution uses
    # acquisition_queue exclusively.
    selected_sources: list[CandidateSource] = Field(default_factory=list)

    acquired_pages: list[PageDocument] = Field(default_factory=list)
    job_detail_pages: list[AIPageInput] = Field(default_factory=list)
    # Stage completion is tracked separately from output presence.  A stage
    # may legitimately produce no output (for example, a page with no job),
    # so downstream lists cannot be used as completion markers.
    analyzed_page_urls: list[str] = Field(default_factory=list)
    extracted_page_urls: list[str] = Field(default_factory=list)
    pending_followups: list[PendingFollowup] = Field(default_factory=list)
    explored_followup_links: list[str] = Field(default_factory=list)
    # History/debug only; runtime scheduling is derived from pending_followups
    # and the canonical followup admission checks.
    processed_followup_urls: list[str] = Field(default_factory=list)
    followup_resolutions: list[dict[str, Any]] = Field(default_factory=list)
    rejected_pages: list[RejectedPage] = Field(default_factory=list)
    page_analysis_traces: list[PageAnalysisTrace] = Field(default_factory=list)   # 暂时保留：后续迁移到 tracing / observability，不作为长期核心 runtime state。

    prepared_jobs: list[JobRecord] = Field(default_factory=list)
    understanding_records: list[JobUnderstandingRecord] = Field(default_factory=list)
    understood_job_keys: list[str] = Field(default_factory=list)
    # Each item is the MatchAnalysisTool envelope: metadata at the top level
    # and the FinalMatchAssessment under ``assessment``.
    match_assessments: list[dict[str, Any]] = Field(default_factory=list)
    matched_job_keys: list[str] = Field(default_factory=list)
    errors: list[AgentError] = Field(default_factory=list)

    @model_validator(mode="after")
    def migrate_selected_sources_to_queue(self) -> "AgentState":
        """Keep old checkpoints usable while the queue becomes authoritative."""

        if not self.acquisition_queue and self.selected_sources:
            from job_radar.tools.web_search.url_utils import normalize_url

            def normalized(value: str) -> str:
                return normalize_url(value)

            handled = {normalized(page.url) for page in self.acquired_pages}
            handled.update(normalized(item.url) for item in self.rejected_pages)
            handled.update(normalized(error.url) for error in self.errors if error.url)
            self.acquisition_queue = [
                source.model_copy(update={"url": normalized(source.url)})
                for source in self.selected_sources
                if normalized(source.url) not in handled
            ]
        return self


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
