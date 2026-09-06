"""Tool entry point for matching understood jobs against a candidate profile."""

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from job_radar.infra.logging import get_logger
from job_radar.infra.llm.ollama import OllamaProvider
from job_radar.profile.models import UserProfile
from job_radar.tools.base import BaseTool
from job_radar.tools.job_extraction.models import JobRecord
from job_radar.tools.job_understanding.models import JobUnderstandingRecord
from job_radar.tools.match_analysis.analyzer import SemanticMatchAnalyzer
from job_radar.tools.match_analysis.models import FinalMatchAssessment


logger = get_logger(__name__)


class MatchAnalysisToolInput(BaseModel):
    """Input for Ollama semantic match analysis."""

    records: list[JobUnderstandingRecord]
    prepared_jobs: list[JobRecord] = Field(default_factory=list)
    profile: UserProfile


class MatchAnalysisToolOutput(BaseModel):
    """Output from Ollama semantic match analysis."""

    assessments: list[dict[str, Any]] = Field(default_factory=list)
    report: dict[str, Any] = Field(default_factory=dict)

    def tool_event_summary(self) -> str:
        return f"assessments={len(self.assessments)} errors={self.report.get('error_count', 0)}"


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
        jobs_by_key = {job.deduplication_key: job for job in data.prepared_jobs}
        for index, record in enumerate(data.records, start=1):
            job = jobs_by_key.get(record.deduplication_key)
            if job is None:
                errors.append({"index": index, "deduplication_key": record.deduplication_key, "reason": "Prepared job was not found."})
                continue
            try:
                assessment: FinalMatchAssessment = analyzer.analyze_understanding(record, job, data.profile)
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
        logger.info(
            "match_analysis analyzed=%s assessments=%s errors=%s",
            len(data.records),
            len(assessments),
            len(errors),
        )
        for item in assessments:
            assessment = item["assessment"]
            logger.info(
                "match_analysis decision title=%s score=%s hard_reject=%s reasons=%s",
                item["title"],
                assessment.get("match_score"),
                any(flag in assessment.get("risk_flags", []) for flag in ("expired_deadline", "graduation_year_mismatch", "graduation_window_mismatch", "excluded_location")),
                "; ".join(assessment.get("match_reasons", [])),
            )
        return MatchAnalysisToolOutput(assessments=assessments, report=report)
