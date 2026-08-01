"""Abstract LLM interface for future AI-backed skills."""

from abc import ABC, abstractmethod

from job_radar.agents.models import PageContent
from job_radar.models.job import RawJobRecord


class LLMClient(ABC):
    """Structured LLM operations used where deterministic code is not enough."""

    @abstractmethod
    def extract_jobs_from_page(self, page: PageContent) -> list[RawJobRecord]:
        """Extract raw job records from collected page content."""
