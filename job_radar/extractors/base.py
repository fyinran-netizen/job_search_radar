"""Extractor interfaces for converting page content into raw job records."""

from abc import ABC, abstractmethod

from job_radar.agents.models import PageContent
from job_radar.models.job import RawJobRecord


class JobExtractor(ABC):
    """Convert collected page content into raw job records."""

    @abstractmethod
    def extract(self, page: PageContent) -> list[RawJobRecord]:
        """Extract one or more raw job records from page content."""
