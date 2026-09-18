"""Tool abstractions and local tool entry points."""

from job_radar.tools.base import BaseTool
from job_radar.tools.executor import ToolExecutor
from job_radar.tools.job_extraction.tool import JobExtractionTool
from job_radar.tools.job_understanding.tool import JobUnderstandingTool
from job_radar.tools.match_analysis.tool import MatchAnalysisTool
from job_radar.tools.page_acquisition.pipeline import BrowserPageTool, PageAcquisitionPipeline

HttpPageTool = PageAcquisitionPipeline
from job_radar.tools.page_acquisition.mock import MockPageTool
from job_radar.tools.page_analysis.tool import (
    PageAnalysisInput,
    PageAnalysisOutput,
    PageAnalysisTool,
)
from job_radar.tools.explore_followups.tool import ExploreFollowupsTool
from job_radar.tools.registry import (
    create_manual_http_tool_executor,
    create_mock_tool_executor,
    create_real_search_tool_executor,
)
from job_radar.tools.web_search.providers.mock import MockWebSearchTool
from job_radar.tools.web_search.providers.tavily import TavilyWebSearchTool
from job_radar.tools.web_search.manual import ManualSourceTool
from job_radar.tools.search_plan import BuildSearchPlanTool, SearchPlan, SearchPlanBuilder

__all__ = [
    "BaseTool",
    "BrowserPageTool",
    "BuildSearchPlanTool",
    "HttpPageTool",
    "PageAcquisitionPipeline",
    "JobExtractionTool",
    "JobUnderstandingTool",
    "ManualSourceTool",
    "MatchAnalysisTool",
    "MockPageTool",
    "MockWebSearchTool",
    "TavilyWebSearchTool",
    "SearchPlan",
    "SearchPlanBuilder",
    "PageAnalysisInput",
    "PageAnalysisOutput",
    "PageAnalysisTool",
    "ExploreFollowupsTool",
    "ToolExecutor",
    "create_manual_http_tool_executor",
    "create_mock_tool_executor",
    "create_real_search_tool_executor",
]
