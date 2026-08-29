"""Tool abstractions and local tool entry points."""

from job_radar.tools.base import BaseTool
from job_radar.tools.executor import ToolExecutor
from job_radar.tools.job_extraction.tool import JobExtractionTool
from job_radar.tools.job_understanding.tool import JobUnderstandingTool
from job_radar.tools.match_analysis.tool import MatchAnalysisTool
from job_radar.tools.page_collection.http import HttpPageTool
from job_radar.tools.page_collection.browser import BrowserPageTool
from job_radar.tools.page_collection.mock import MockPageTool
from job_radar.tools.page_processing.tool import (
    PageProcessingInput,
    PageProcessingOutput,
    PageProcessingTool,
)
from job_radar.tools.registry import (
    create_manual_http_tool_executor,
    create_mock_tool_executor,
    create_real_search_tool_executor,
)
from job_radar.tools.web_search.providers.mock import MockWebSearchTool
from job_radar.tools.web_search.providers.tavily import TavilyWebSearchTool
from job_radar.tools.web_search.source_selection import ManualSourceTool

__all__ = [
    "BaseTool",
    "BrowserPageTool",
    "HttpPageTool",
    "JobExtractionTool",
    "JobUnderstandingTool",
    "ManualSourceTool",
    "MatchAnalysisTool",
    "MockPageTool",
    "MockWebSearchTool",
    "TavilyWebSearchTool",
    "PageProcessingInput",
    "PageProcessingOutput",
    "PageProcessingTool",
    "ToolExecutor",
    "create_manual_http_tool_executor",
    "create_mock_tool_executor",
    "create_real_search_tool_executor",
]
