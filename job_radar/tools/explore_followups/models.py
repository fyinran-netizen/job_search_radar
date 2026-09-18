"""Data contracts for deterministic follow-up exploration."""

from typing import Any, Literal

from pydantic import BaseModel, Field

from job_radar.tools.page_analysis.models import PendingFollowup, PendingKind
from job_radar.tools.web_search.models import CandidateSource


class ExploreFollowupsInput(BaseModel):
    """Pending items and URL state supplied by the Agent action."""

    pending_followups: list[PendingFollowup] = Field(default_factory=list)
    excluded_urls: set[str] = Field(default_factory=set)
    explored_links: set[str] = Field(default_factory=set)


class FollowupResolution(BaseModel):
    """Deterministic result for one pending follow-up."""

    followup_url: str
    stage: Literal["collection", "pre_extraction", "post_extraction"]
    pending_kind: PendingKind
    status: Literal["explored", "unsupported", "no_usable_links", "already_explored"]
    discovered_count: int = 0
    skipped_count: int = 0
    reason: str = ""
    evidence: dict[str, Any] = Field(default_factory=dict)


class ExploreFollowupsOutput(BaseModel):
    """New executable sources and auditable resolution metadata."""

    sources: list[CandidateSource] = Field(default_factory=list)
    explored_links: list[str] = Field(default_factory=list)
    resolutions: list[FollowupResolution] = Field(default_factory=list)

    def tool_event_summary(self) -> str:
        return (
            f"sources={len(self.sources)} "
            f"explored_links={len(self.explored_links)} "
            f"resolutions={len(self.resolutions)}"
        )
