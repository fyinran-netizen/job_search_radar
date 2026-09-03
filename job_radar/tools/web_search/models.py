"""Search result data contracts (SearchPlan lives in search_plan)."""

from pydantic import BaseModel

from job_radar.tools.search_plan.models import SearchPlan


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


