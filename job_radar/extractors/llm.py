"""LLM-backed extractor adapters.

No concrete API client is configured in phase one. This module defines the
boundary so a future LLM implementation can replace deterministic extraction
without changing the agent, pipeline, repository, or UI layers.
"""

from typing import Protocol

from job_radar.extractors.base import JobExtractor
from job_radar.models.job import RawJobRecord
from job_radar.models.tool import PageContent


class PageExtractionClient(Protocol):
    """Client protocol for AI-backed page extraction tasks."""

    def extract_jobs_from_page(self, page: PageContent) -> list[RawJobRecord]:
        """Extract raw job records from collected page content."""


class LLMJobExtractor(JobExtractor):
    """Use an LLM client to extract structured job records from page content."""

    def __init__(self, llm_client: PageExtractionClient) -> None:
        self.llm_client = llm_client

    def extract(self, page: PageContent) -> list[RawJobRecord]:
        """Delegate extraction to the configured LLM client."""

        return self.llm_client.extract_jobs_from_page(page)


class UnconfiguredLLMJobExtractor(JobExtractor):
    """Fail explicitly when an LLM extractor is requested without a client."""

    def extract(self, page: PageContent) -> list[RawJobRecord]:
        """Raise a clear error instead of silently pretending LLM extraction works."""

        raise RuntimeError("LLM job extraction is not configured. Provide an LLMClient implementation first.")
