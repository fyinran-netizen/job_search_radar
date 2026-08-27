"""Job semantic tools used after page routing."""

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from job_radar.ai.providers.ollama import OllamaProvider
from job_radar.ai.tasks.job_extraction import AIJobExtractionClient, AIPageInput
from job_radar.ai.tasks.job_understanding import JobUnderstandingAnalyzer
from job_radar.ai.tasks.match_analysis import SemanticMatchAnalyzer
from job_radar.models.job import JobRecord, RawJobRecord
from job_radar.models.match import FinalMatchAssessment
from job_radar.models.profile import UserProfile
from job_radar.models.understanding import JobUnderstandingRecord
from job_radar.tools.base import BaseTool


class JobExtractionInput(BaseModel):
    """Input for Ollama job extraction."""

    pages: list[AIPageInput]


class JobExtractionOutput(BaseModel):
    """Output from Ollama job extraction."""

    raw_records: list[RawJobRecord] = Field(default_factory=list)
    report: dict[str, Any] = Field(default_factory=dict)

    def tool_event_summary(self) -> str:
        return (
            f"raw_records={len(self.raw_records)} "
            f"errors={self.report.get('error_count', 0)}"
        )


class JobUnderstandingToolInput(BaseModel):
    """Input for Ollama job understanding."""

    jobs: list[JobRecord]
    profile: UserProfile


class JobUnderstandingToolOutput(BaseModel):
    """Output from Ollama job understanding."""

    records: list[JobUnderstandingRecord] = Field(default_factory=list)
    report: dict[str, Any] = Field(default_factory=dict)

    def tool_event_summary(self) -> str:
        return (
            f"understandings={len(self.records)} "
            f"errors={self.report.get('error_count', 0)}"
        )


class MatchAnalysisToolInput(BaseModel):
    """Input for Ollama semantic match analysis."""

    records: list[JobUnderstandingRecord]
    profile: UserProfile


class MatchAnalysisToolOutput(BaseModel):
    """Output from Ollama semantic match analysis."""

    assessments: list[dict[str, Any]] = Field(default_factory=list)
    report: dict[str, Any] = Field(default_factory=dict)

    def tool_event_summary(self) -> str:
        return (
            f"assessments={len(self.assessments)} "
            f"errors={self.report.get('error_count', 0)}"
        )


class JobExtractionTool(BaseTool):
    """Extract jobs from routed job-detail pages with Ollama."""

    name = "job_extraction"

    def __init__(self, provider: OllamaProvider, timeout_seconds: int = 240) -> None:
        self.provider = provider
        self.timeout_seconds = timeout_seconds

    def run(self, payload: BaseModel | dict[str, Any]) -> JobExtractionOutput:
        data = payload if isinstance(payload, JobExtractionInput) else JobExtractionInput.model_validate(payload)
        client = AIJobExtractionClient(self.provider, timeout_seconds=self.timeout_seconds)
        records: list[RawJobRecord] = []
        errors = []
        for index, page in enumerate(data.pages, start=1):
            try:
                records.extend(client.extract_jobs_from_input(page))
            except Exception as exc:
                errors.append({"index": index, "url": page.url, "title": page.title, "reason": str(exc)})
        report = {
            "extracted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "provider": "ollama",
            "ollama_model": self.provider.model,
            "page_count": len(data.pages),
            "extracted_count": len(records),
            "error_count": len(errors),
            "errors": errors,
        }
        return JobExtractionOutput(raw_records=records, report=report)


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
        return JobUnderstandingToolOutput(records=records, report=report)


class MatchAnalysisTool(BaseTool):
    """Analyze understood jobs against a profile with Ollama."""

    name = "match_analysis"

    def __init__(self, provider: OllamaProvider, timeout_seconds: int = 180) -> None:
        self.provider = provider
        self.timeout_seconds = timeout_seconds

    def run(self, payload: BaseModel | dict[str, Any]) -> MatchAnalysisToolOutput:
        data = payload if isinstance(payload, MatchAnalysisToolInput) else MatchAnalysisToolInput.model_validate(payload)
        analyzer = SemanticMatchAnalyzer(self.provider, timeout_seconds=self.timeout_seconds)
        assessments = []
        errors = []
        for index, record in enumerate(data.records, start=1):
            job = record.job
            try:
                assessment: FinalMatchAssessment = analyzer.analyze_understanding(record, data.profile)
            except Exception as exc:
                errors.append(
                    {
                        "index": index,
                        "company_name": job.company_name,
                        "title": job.title,
                        "deduplication_key": job.deduplication_key,
                        "reason": str(exc),
                    }
                )
                continue
            assessments.append(
                {
                    "deduplication_key": job.deduplication_key,
                    "company_name": job.company_name,
                    "title": job.title,
                    "assessment": assessment.model_dump(),
                }
            )
        report = {
            "analyzed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "provider": "ollama",
            "ollama_model": self.provider.model,
            "understanding_count": len(data.records),
            "assessment_count": len(assessments),
            "error_count": len(errors),
            "errors": errors,
        }
        return MatchAnalysisToolOutput(assessments=assessments, report=report)
