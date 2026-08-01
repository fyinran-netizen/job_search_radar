"""Factories for tool scheduler setup."""

from job_radar.agents.models import CandidateSource
from job_radar.tools.base import ToolScheduler
from job_radar.tools.http_page_collector import HttpPageCollectorTool
from job_radar.tools.manual_sources import ManualSourceTool
from job_radar.tools.mock_page_collector import MockPageCollectorTool
from job_radar.tools.mock_web_search import MockWebSearchTool


def create_mock_tool_scheduler() -> ToolScheduler:
    """Create the local mock tool scheduler used in phase one."""

    return ToolScheduler([MockWebSearchTool(), MockPageCollectorTool()])


def create_manual_http_tool_scheduler(sources: list[CandidateSource]) -> ToolScheduler:
    """Create a scheduler that uses manual URLs and real HTTP page collection."""

    return ToolScheduler([ManualSourceTool(sources), HttpPageCollectorTool()])
