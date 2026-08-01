"""Deterministic mock LLM implementation for local development."""

from job_radar.agents.models import PageContent
from job_radar.extractors.rule_based import RuleBasedJobExtractor
from job_radar.llm.base import LLMClient
from job_radar.models.job import RawJobRecord


class MockLLMClient(LLMClient):
    """Mock LLM client with deterministic structured outputs."""

    def __init__(self, extractor: RuleBasedJobExtractor | None = None) -> None:
        self.extractor = extractor or RuleBasedJobExtractor()

    def extract_jobs_from_page(self, page: PageContent) -> list[RawJobRecord]:
        """Extract records from mock page text blocks."""

        return self.extractor.extract(page)
