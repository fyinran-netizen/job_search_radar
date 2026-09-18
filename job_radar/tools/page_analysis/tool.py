"""Agent-facing page analysis: cleaning, quality checks, and classification."""

from datetime import datetime, timezone
from time import perf_counter
from typing import Any

from pydantic import BaseModel, Field

from job_radar.infra.llm.base import AIProvider
from job_radar.infra.logging import get_logger
from job_radar.tools.base import BaseTool
from job_radar.tools.page_acquisition.models import PageDocument, RejectedPage
from job_radar.tools.page_analysis.models import AIPageInput, PageAnalysisTrace, PendingFollowup
from job_radar.tools.page_analysis.semantic_classification import PageSemanticClassifier, pending_followup_from_semantic_classification
from job_radar.tools.page_analysis.preparation import prepare_page

logger = get_logger(__name__)


class PageAnalysisInput(BaseModel):
    """Already acquired documents to clean and classify."""

    pages: list[PageDocument]
    min_text_length: int = 300
    max_text_chars: int = 12000


class PageAnalysisOutput(BaseModel):
    """Analysis results; no acquisition or recovery is performed here."""

    accepted_pages: list[AIPageInput] = Field(default_factory=list)
    pending_followups: list[PendingFollowup] = Field(default_factory=list)
    rejected_pages: list[RejectedPage] = Field(default_factory=list)
    traces: list[PageAnalysisTrace] = Field(default_factory=list)
    report: dict[str, Any] = Field(default_factory=dict)

    def tool_event_summary(self) -> str:
        return f"accepted={len(self.accepted_pages)} pending={len(self.pending_followups)} rejected={len(self.rejected_pages)} errors={self.report.get('error_count', 0)}"


class PageAnalysisTool(BaseTool):
    """Clean, quality-check, and semantically classify acquired documents."""

    name = "analyze_page"

    def __init__(self, provider: AIProvider, timeout_seconds: int = 90) -> None:
        self.provider = provider
        self.timeout_seconds = timeout_seconds

    def run(self, payload: BaseModel | dict[str, Any]) -> PageAnalysisOutput:
        data = payload if isinstance(payload, PageAnalysisInput) else PageAnalysisInput.model_validate(payload)
        started = perf_counter()
        cleaned: list[AIPageInput] = []
        traces: list[PageAnalysisTrace] = []
        pending: list[PendingFollowup] = []
        rejected: list[RejectedPage] = []
        errors: list[dict[str, Any]] = []
        for acquired in data.pages:
            try:
                prepared = prepare_page(acquired, max_text_chars=data.max_text_chars)
            except Exception as exc:
                errors.append({"url": acquired.url, "title": acquired.title, "reason": str(exc)})
                traces.append(PageAnalysisTrace(url=acquired.url))
                pending.append(_analysis_pending(acquired, f"page_cleaning_failed: {exc}"))
                continue
            page = prepared.page
            trace = prepared.trace
            traces.append(trace)
            quality_reason = _quality_failure(acquired.model_copy(update={"text": page.visible_text}), data.min_text_length)
            if quality_reason:
                rejected.append(RejectedPage(url=page.url, source_name=page.source_name, title=page.title, reasons=[quality_reason], text_length=len(page.visible_text.strip()), metadata=acquired.metadata))
                continue
            cleaned.append(page)

        accepted: list[AIPageInput] = []
        classifications: list[dict[str, Any]] = []
        classifier = PageSemanticClassifier(self.provider, timeout_seconds=self.timeout_seconds)
        for page in cleaned:
            try:
                classification = classifier.classify(page)
                classifications.append({"url": page.url, "title": page.title, "classification": classification.model_dump()})
                if classification.is_job_detail_page:
                    accepted.append(page)
                else:
                    pending.append(pending_followup_from_semantic_classification(page, classification))
            except Exception as exc:
                errors.append({"url": page.url, "title": page.title, "reason": str(exc)})
                pending.append(_analysis_pending(page, f"semantic_classification_failed: {exc}"))

        report = {"started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "input_page_count": len(data.pages), "cleaned_page_count": len(cleaned), "accepted_page_count": len(accepted), "pending_followup_count": len(pending), "rejected_count": len(rejected), "error_count": len(errors), "errors": errors, "classifications": classifications, "elapsed_ms": round((perf_counter() - started) * 1000, 1)}
        logger.info("analyze_page elapsed_ms=%.1f accepted=%s pending=%s rejected=%s errors=%s", report["elapsed_ms"], len(accepted), len(pending), len(rejected), len(errors))
        return PageAnalysisOutput(accepted_pages=accepted, pending_followups=pending, rejected_pages=rejected, traces=traces, report=report)


def _quality_failure(page: PageDocument, minimum: int) -> str | None:
    evidence = page.fetch_evidence
    if evidence.error or (evidence.status_code is not None and not 200 <= evidence.status_code < 400):
        return f"acquisition_failed: {evidence.error or evidence.status_code}"
    if len(page.text.strip()) < minimum:
        return f"insufficient_analyzed_text: {len(page.text.strip())} < {minimum}"
    return None


def _analysis_pending(page: AIPageInput | PageDocument, reason: str) -> PendingFollowup:
    metadata = page.metadata if isinstance(page, PageDocument) else {}
    company_name = metadata.get("company_name", getattr(page, "source_company_name", None))
    company_type = metadata.get("company_type", getattr(page, "company_type", None))
    return PendingFollowup(url=page.url, final_url=metadata.get("final_url"), title=page.title, source_name=page.source_name, company_name=company_name, company_type=company_type, is_official=bool(metadata.get("is_official", getattr(page, "is_official", False))), pending_kind="review_required", reasons=[reason], evidence={}, suggested_next_action="manual_review", priority=50, stage="pre_extraction")
