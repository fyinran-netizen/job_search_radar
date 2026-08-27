"""Page routing tools used by the real E2E workflow."""

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from job_radar.ai.providers.ollama import OllamaProvider
from job_radar.ai.tasks.job_extraction import AIPageInput, build_ai_page_input
from job_radar.ai.tasks.page_classification import (
    PageSemanticClassifier,
    pending_followup_from_semantic_classification,
)
from job_radar.models.page_triage import PendingFollowup
from job_radar.models.search import SearchPlan
from job_radar.models.tool import PageContent
from job_radar.pipeline.page_filter import PendingPage, RejectedPage, filter_pages
from job_radar.tools.base import BaseTool


class PageFilterInput(BaseModel):
    """Input for deterministic Stage 1 technical page routing."""

    pages: list[PageContent]
    search_plan: SearchPlan | None = None
    min_text_length: int = 300
    pending_pages: list[PendingPage] = Field(default_factory=list)
    rejected_pages: list[RejectedPage] = Field(default_factory=list)


class PageFilterOutput(BaseModel):
    """Output from deterministic Stage 1 technical page routing."""

    readable_pages: list[PageContent] = Field(default_factory=list)
    pending_pages: list[PendingPage] = Field(default_factory=list)
    rejected_pages: list[RejectedPage] = Field(default_factory=list)

    def tool_event_summary(self) -> str:
        return (
            f"readable={len(self.readable_pages)} "
            f"pending={len(self.pending_pages)} rejected={len(self.rejected_pages)}"
        )


class PageCleaningInput(BaseModel):
    """Input for page cleaning."""

    pages: list[PageContent]
    max_text_chars: int = 12000


class PageCleaningOutput(BaseModel):
    """Cleaned page inputs for semantic routing and extraction."""

    cleaned_pages: list[AIPageInput] = Field(default_factory=list)
    report: dict[str, Any] = Field(default_factory=dict)

    def tool_event_summary(self) -> str:
        return f"cleaned_pages={len(self.cleaned_pages)}"


class PageClassificationInput(BaseModel):
    """Input for Stage 2 semantic page routing."""

    pages: list[AIPageInput]


class PageClassificationOutput(BaseModel):
    """Output from Stage 2 semantic page routing."""

    jd_pages: list[AIPageInput] = Field(default_factory=list)
    pending_followups: list[PendingFollowup] = Field(default_factory=list)
    report: dict[str, Any] = Field(default_factory=dict)

    def tool_event_summary(self) -> str:
        return (
            f"jd_pages={len(self.jd_pages)} "
            f"pending={len(self.pending_followups)} "
            f"errors={self.report.get('error_count', 0)}"
        )


class PageFilterTool(BaseTool):
    """Run deterministic Stage 1 technical page routing."""

    name = "page_filter"

    def run(self, payload: BaseModel | dict[str, Any]) -> PageFilterOutput:
        data = payload if isinstance(payload, PageFilterInput) else PageFilterInput.model_validate(payload)
        result = filter_pages(
            data.pages,
            search_plan=data.search_plan,
            min_text_length=data.min_text_length,
        )
        return PageFilterOutput(
            readable_pages=result.readable_pages,
            pending_pages=[*data.pending_pages, *result.pending_pages],
            rejected_pages=[*data.rejected_pages, *result.rejected_pages],
        )


class PageCleaningTool(BaseTool):
    """Clean readable pages into AIPageInput records."""

    name = "page_cleaning"

    def run(self, payload: BaseModel | dict[str, Any]) -> PageCleaningOutput:
        data = payload if isinstance(payload, PageCleaningInput) else PageCleaningInput.model_validate(payload)
        cleaned_pages = [build_ai_page_input(page, max_text_chars=data.max_text_chars) for page in data.pages]
        report = {
            "cleaned_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "page_count": len(cleaned_pages),
            "max_text_chars": data.max_text_chars,
            "pages": [
                {
                    "url": page.url,
                    "title": page.title,
                    "source_name": page.source_name,
                    "visible_text_chars": len(cleaned.visible_text),
                    "important_link_count": len(cleaned.important_links),
                }
                for page, cleaned in zip(data.pages, cleaned_pages, strict=True)
            ],
        }
        return PageCleaningOutput(cleaned_pages=cleaned_pages, report=report)


class PageClassificationTool(BaseTool):
    """Run Stage 2 semantic page routing with Ollama."""

    name = "page_classification"

    def __init__(self, provider: OllamaProvider, timeout_seconds: int = 90) -> None:
        self.provider = provider
        self.timeout_seconds = timeout_seconds

    def run(self, payload: BaseModel | dict[str, Any]) -> PageClassificationOutput:
        data = payload if isinstance(payload, PageClassificationInput) else PageClassificationInput.model_validate(payload)
        classifier = PageSemanticClassifier(self.provider, timeout_seconds=self.timeout_seconds)
        jd_pages: list[AIPageInput] = []
        pending_followups: list[PendingFollowup] = []
        items = []
        errors = []
        for index, page in enumerate(data.pages, start=1):
            try:
                classification = classifier.classify(page)
            except Exception as exc:
                errors.append({"index": index, "url": page.url, "title": page.title, "reason": str(exc)})
                continue
            items.append(
                {
                    "index": index,
                    "url": page.url,
                    "title": page.title,
                    "source_name": page.source_name,
                    "classification": classification.model_dump(),
                }
            )
            if classification.is_job_detail_page:
                jd_pages.append(page)
            else:
                pending_followups.append(pending_followup_from_semantic_classification(page, classification))
        report = {
            "classified_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "provider": "ollama",
            "ollama_model": self.provider.model,
            "input_page_count": len(data.pages),
            "jd_page_count": len(jd_pages),
            "pending_followup_count": len(pending_followups),
            "error_count": len(errors),
            "classifications": items,
            "errors": errors,
        }
        return PageClassificationOutput(jd_pages=jd_pages, pending_followups=pending_followups, report=report)
