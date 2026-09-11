"""Factories for tool executor setup."""

from job_radar.infra.llm.base import AIProvider
from job_radar.tools.executor import ToolExecutor
from job_radar.tools.job_extraction.tool import JobExtractionTool
from job_radar.tools.job_understanding.tool import JobUnderstandingTool
from job_radar.tools.match_analysis.tool import MatchAnalysisTool
from job_radar.tools.page_acquisition.http import HttpPageTool
from job_radar.tools.page_acquisition.mock import MockPageTool
from job_radar.tools.page_analysis.tool import PageAnalysisTool
from job_radar.tools.search_plan import BuildSearchPlanTool
from job_radar.tools.web_search.models import CandidateSource
from job_radar.tools.web_search.providers.mock import MockWebSearchTool
from job_radar.tools.web_search.providers.tavily import TavilyWebSearchTool
from job_radar.tools.web_search.manual import ManualSourceTool


def create_mock_tool_executor() -> ToolExecutor:
    """Create the local mock tool executor used in phase one."""

    return ToolExecutor(
        [
            BuildSearchPlanTool(),
            MockWebSearchTool(),
            MockPageTool(),
        ]
    )


def create_manual_http_tool_executor(
    sources: list[CandidateSource],
) -> ToolExecutor:
    """Create an executor that uses manual URLs and real HTTP page acquisition."""

    return ToolExecutor(
        [
            BuildSearchPlanTool(),
            ManualSourceTool(sources),
            HttpPageTool(),
        ]
    )


def create_real_search_tool_executor(
    analyze_page_provider: AIProvider,
    job_extraction_provider: AIProvider,
    job_understanding_provider: AIProvider,
    match_analysis_provider: AIProvider,
    max_sources: int = 10,
) -> ToolExecutor:
    """Create the real E2E executor with one Page Analysis capability."""

    return ToolExecutor(
        [
            BuildSearchPlanTool(),
            TavilyWebSearchTool(
                max_sources=max_sources
            ),
            HttpPageTool(),
            PageAnalysisTool(
                provider=analyze_page_provider
            ),
            JobExtractionTool(
                job_extraction_provider
            ),
            JobUnderstandingTool(
                job_understanding_provider
            ),
            MatchAnalysisTool(
                match_analysis_provider
            ),
        ]
    )
