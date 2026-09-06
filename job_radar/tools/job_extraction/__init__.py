"""Job extraction capability."""

from job_radar.tools.page_analysis.models import AIPageInput
from job_radar.tools.job_extraction.models import JobRecord, RawJobRecord

from job_radar.tools.job_extraction.tool import (
    JobExtractionInput,
    JobExtractionOutput,
    JobExtractionTool,
)

__all__ = [
    "AIPageInput",
    "JobRecord",
    "RawJobRecord",
    "JobExtractionInput",
    "JobExtractionOutput",
    "JobExtractionTool",
]
