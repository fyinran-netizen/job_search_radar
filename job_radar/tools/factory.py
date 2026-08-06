"""Factories for tool executor setup."""

from job_radar.models.search import CandidateSource
from job_radar.tools.executor import ToolExecutor
from job_radar.tools.functions.codex_web_search import CodexWebSearchTool
from job_radar.tools.functions.http_page import HttpPageTool
from job_radar.tools.functions.manual_sources import ManualSourceTool
from job_radar.tools.functions.mock_page import MockPageTool
from job_radar.tools.functions.mock_web_search import MockWebSearchTool


def create_mock_tool_executor() -> ToolExecutor:
    """Create the local mock tool executor used in phase one."""

    return ToolExecutor([MockWebSearchTool(), MockPageTool()])


def create_manual_http_tool_executor(sources: list[CandidateSource]) -> ToolExecutor:
    """Create an executor that uses manual URLs and real HTTP page collection."""

    return ToolExecutor([ManualSourceTool(sources), HttpPageTool()])


def create_codex_web_search_tool_executor(max_sources: int = 10) -> ToolExecutor:
    """Create an executor that uses Codex CLI-backed web search only."""

    return ToolExecutor([CodexWebSearchTool(max_sources=max_sources)])
