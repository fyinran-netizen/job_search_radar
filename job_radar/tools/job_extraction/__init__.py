"""Job extraction capability."""

from job_radar.tools.page_analysis.models import AIPageInput
from job_radar.tools.job_extraction.models import BasicGateResult, JobRecord, RawJobRecord
from job_radar.tools.job_extraction.backend_gate.gate import evaluate_basic_gate

from job_radar.tools.job_extraction.tool import (
    JobExtractionInput,
    JobExtractionOutput,
    JobExtractionTool,
)

__all__ = [
    "AIPageInput",
    "JobRecord",
    "RawJobRecord",
    "BasicGateResult",
    "evaluate_basic_gate",
    "JobExtractionInput",
    "JobExtractionOutput",
    "JobExtractionTool",
]
