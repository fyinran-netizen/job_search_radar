"""Collector base protocol."""

from abc import ABC, abstractmethod

from job_radar.models.job import RawJobRecord


class BaseCollector(ABC):
    """Base interface for job collectors."""

    source_name: str

    @abstractmethod
    def collect(self) -> list[RawJobRecord]:
        """Collect raw job records from a source."""
