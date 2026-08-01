"""Mock web search tool for local agent testing."""

from typing import Any

from pydantic import BaseModel

from job_radar.agents.models import CandidateSource, SearchPlan
from job_radar.tools.base import BaseTool


class MockWebSearchTool(BaseTool):
    """Return deterministic candidate URLs without network access."""

    name = "web_search"

    def run(self, payload: BaseModel | dict[str, Any]) -> list[CandidateSource]:
        """Return mock candidate sources for a search plan."""

        plan = payload if isinstance(payload, SearchPlan) else SearchPlan.model_validate(payload)
        keyword_hint = ", ".join(plan.keywords[:3])
        return [
            CandidateSource(
                url="mock://future-bank/campus",
                title="Future Bank Technology Graduate Careers",
                source_name="Future Bank Careers",
                is_official=True,
                relevance_score=94,
                reason=f"Official bank graduate source matching: {keyword_hint}",
            ),
            CandidateSource(
                url="mock://global-tech/graduates",
                title="Global Tech Graduate Jobs",
                source_name="Global Tech Careers",
                is_official=True,
                relevance_score=88,
                reason="Official technology graduate source with software and data roles.",
            ),
            CandidateSource(
                url="mock://unrelated-forum/thread",
                title="General career discussion thread",
                source_name="Unrelated Forum",
                is_official=False,
                relevance_score=28,
                reason="Low-confidence discussion page, not a direct application source.",
            ),
        ]
