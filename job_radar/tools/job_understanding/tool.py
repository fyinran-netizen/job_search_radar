"""Tool entry point for understanding prepared jobs."""

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from job_radar.infra.logging import get_logger
from job_radar.infra.llm.ollama import OllamaProvider
from job_radar.profile.models import UserProfile
from job_radar.tools.base import BaseTool
from job_radar.tools.job_extraction.models import JobRecord
from job_radar.tools.job_understanding.analyzer import JobUnderstandingAnalyzer
from job_radar.tools.job_understanding.models import JobUnderstandingRecord


logger = get_logger(__name__)


class JobUnderstandingToolInput(BaseModel):
    """Input for Ollama job understanding."""

    jobs: list[JobRecord]
    profile: UserProfile


class JobUnderstandingToolOutput(BaseModel):
    """Output from Ollama job understanding."""

    records: list[JobUnderstandingRecord] = Field(default_factory=list)
    report: dict[str, Any] = Field(default_factory=dict)

    def tool_event_summary(self) -> str:
        return f"understandings={len(self.records)} errors={self.report.get('error_count', 0)}"


class JobUnderstandingTool(BaseTool):
    """Understand prepared jobs with Ollama and deterministic basic gates."""

    name = "job_understanding"

    def __init__(self, provider: OllamaProvider, timeout_seconds: int = 180) -> None:
        self.provider = provider
        self.timeout_seconds = timeout_seconds

    def run(self, payload: BaseModel | dict[str, Any]) -> JobUnderstandingToolOutput:
        data = payload if isinstance(payload, JobUnderstandingToolInput) else JobUnderstandingToolInput.model_validate(payload)
        analyzer = JobUnderstandingAnalyzer(self.provider, timeout_seconds=self.timeout_seconds)
        records: list[JobUnderstandingRecord] = []
        errors = []
        skipped_count = 0
        for index, job in enumerate(data.jobs, start=1):
            try:
                record = analyzer.understand(job, data.profile)
            except Exception as exc:
                errors.append(
                    {
                        "index": index,
                        "company_name": getattr(job, "company_name", None),
                        "title": getattr(job, "title", None),
                        "deduplication_key": getattr(job, "deduplication_key", None),
                        "reason": str(exc),
                    }
                )
                continue
            if record.source == "skipped_by_basic_gate":
                skipped_count += 1
            records.append(record)
        report = {
            "understood_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "provider": "ollama",
            "ollama_model": self.provider.model,
            "prepared_count": len(data.jobs),
            "understanding_count": len(records),
            "skipped_by_basic_gate_count": skipped_count,
            "error_count": len(errors),
            "errors": errors,
        }
        logger.info(
            "job_understanding prepared=%s understood=%s skipped=%s errors=%s",
            len(data.jobs),
            len(records),
            skipped_count,
            len(errors),
        )
        return JobUnderstandingToolOutput(records=records, report=report)
