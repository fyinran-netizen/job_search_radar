"""Factories for tool executor setup."""

from job_radar.ai.providers.ollama import OllamaProvider
from job_radar.models.search import CandidateSource
from job_radar.tools.executor import ToolExecutor
from job_radar.tools.functions.codex_web_search import CodexWebSearchTool
from job_radar.tools.functions.http_page import HttpPageTool
from job_radar.tools.functions.manual_sources import ManualSourceTool
from job_radar.tools.functions.mock_page import MockPageTool
from job_radar.tools.functions.mock_web_search import MockWebSearchTool
from job_radar.tools.functions.job_semantics import (
    JobExtractionTool,
    JobUnderstandingTool,
    MatchAnalysisTool,
)
from job_radar.tools.functions.page_processing import (
    PageClassificationTool,
    PageCleaningTool,
    PageFilterTool,
)


def create_mock_tool_executor() -> ToolExecutor:
    """Create the local mock tool executor used in phase one."""

    return ToolExecutor([MockWebSearchTool(), MockPageTool()])


def create_manual_http_tool_executor(sources: list[CandidateSource]) -> ToolExecutor:
    """Create an executor that uses manual URLs and real HTTP page collection."""

    return ToolExecutor([ManualSourceTool(sources), HttpPageTool()])


def create_real_search_tool_executor(
    page_classification_provider: OllamaProvider,
    job_extraction_provider: OllamaProvider,
    job_understanding_provider: OllamaProvider,
    match_analysis_provider: OllamaProvider,
    max_sources: int = 10,
) -> ToolExecutor:
    """Create the real E2E executor using Codex search and Ollama semantic tools."""

    return ToolExecutor(
        [
            CodexWebSearchTool(max_sources=max_sources),
            HttpPageTool(),
            PageFilterTool(),
            PageCleaningTool(),
            PageClassificationTool(page_classification_provider),
            JobExtractionTool(job_extraction_provider),
            JobUnderstandingTool(job_understanding_provider),
            MatchAnalysisTool(match_analysis_provider),
        ]
    )
