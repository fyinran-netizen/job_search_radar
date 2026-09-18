"""Page acquisition tool package."""

from job_radar.tools.page_acquisition.pipeline import BrowserPageTool, PageAcquisitionPipeline
from job_radar.tools.page_acquisition.mock import MockPageTool
from job_radar.tools.page_acquisition.models import PageDocument

HttpPageTool = PageAcquisitionPipeline

__all__ = ["BrowserPageTool", "HttpPageTool", "MockPageTool", "PageAcquisitionPipeline", "PageDocument"]
