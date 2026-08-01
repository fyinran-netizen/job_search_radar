"""LLM-backed extractor adapters.

No concrete API client is configured in phase one. This module defines the
boundary so a future LLM implementation can replace deterministic extraction
without changing the agent, pipeline, repository, or UI layers.
"""

from job_radar.agents.models import PageContent
from job_radar.extractors.base import JobExtractor
from job_radar.llm.base import LLMClient
from job_radar.models.job import RawJobRecord


class LLMJobExtractor(JobExtractor):
    """Use an LLM client to extract structured job records from page content."""

    def __init__(self, llm_client: LLMClient) -> None:
        self.llm_client = llm_client

    def extract(self, page: PageContent) -> list[RawJobRecord]:
        """Delegate extraction to the configured LLM client."""

        return self.llm_client.extract_jobs_from_page(page)


class UnconfiguredLLMJobExtractor(JobExtractor):
    """Fail explicitly when an LLM extractor is requested without a client."""

    def extract(self, page: PageContent) -> list[RawJobRecord]:
        """Raise a clear error instead of silently pretending LLM extraction works."""

        raise RuntimeError("LLM job extraction is not configured. Provide an LLMClient implementation first.")
