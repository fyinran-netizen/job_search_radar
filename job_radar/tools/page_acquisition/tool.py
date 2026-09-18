"""Tool entry points for page acquisition."""

from job_radar.tools.page_acquisition.pipeline import BrowserPageTool, PageAcquisitionPipeline
from job_radar.tools.page_acquisition.mock import MockPageTool

HttpPageTool = PageAcquisitionPipeline

__all__ = ["BrowserPageTool", "HttpPageTool", "MockPageTool", "PageAcquisitionPipeline"]
