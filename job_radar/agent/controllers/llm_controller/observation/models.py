"""Small, sectioned observation models exposed to the controller model."""

from __future__ import annotations

from pydantic import BaseModel, Field

from job_radar.agent.action_names import AgentActionName


class CommonObservation(BaseModel):
    available_actions: list[AgentActionName]
    last_action: AgentActionName | None = None
    last_action_summary: str | None = None
    stage: str | None = None
    round_index: int
    max_rounds: int
    profile_present: bool
    status: str
    remaining_action_call_budget: dict[AgentActionName, int] = Field(default_factory=dict)


class SearchObservation(BaseModel):
    candidate_source_count: int
    selected_source_count: int
    remaining_query_count: int
    remaining_source_count: int
    last_search_outcome: str | None = None


class PageObservation(BaseModel):
    acquired_page_count: int
    job_detail_page_count: int
    pages_to_analyze: int
    pages_to_extract: int


class JobObservation(BaseModel):
    prepared_job_count: int
    understanding_record_count: int
    jobs_to_understand: int
    records_to_match: int


class ControllerObservation(BaseModel):
    common: CommonObservation
    search: SearchObservation | None = None
    pages: PageObservation | None = None
    jobs: JobObservation | None = None


__all__ = [
    "CommonObservation",
    "ControllerObservation",
    "JobObservation",
    "PageObservation",
    "SearchObservation",
]
