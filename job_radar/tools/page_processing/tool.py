"""Agent-facing Page Processing Tool."""

from datetime import datetime, timezone
from time import perf_counter
from typing import Any

from pydantic import BaseModel, Field

from job_radar.infra.logging import get_logger
from job_radar.infra.llm.base import AIProvider
from job_radar.tools.base import BaseTool
from job_radar.tools.job_extraction.models import AIPageInput
from job_radar.tools.job_extraction.extraction import build_ai_page_input
from job_radar.tools.page_collection.models import (
    PageContent,
)
from job_radar.tools.page_processing.models import (
    PendingFollowup,
)
from job_radar.tools.page_processing.recovery import (
    recover_page,
)
from job_radar.tools.page_processing.semantic_classification import (
    PageSemanticClassifier,
    pending_followup_from_semantic_classification,
)
from job_radar.tools.page_processing.technical_triage import (
    RejectedPage,
    triage_pages,
)
from job_radar.tools.web_search.models import (
    SearchPlan,
)
from job_radar.tools.page_processing.cleaning import parse_collected_page


logger = get_logger(__name__)


class PageProcessingInput(BaseModel):
    """Input for the complete Page Processing capability."""

    pages: list[PageContent]

    search_plan: SearchPlan | None = None

    min_text_length: int = 300
    max_text_chars: int = 12000


class PageProcessingOutput(BaseModel):
    """Final processing output with semantic classification follow-ups."""

    accepted_pages: list[AIPageInput] = Field(
        default_factory=list
    )

    pending_followups: list[PendingFollowup] = Field(
        default_factory=list
    )

    rejected_pages: list[RejectedPage] = Field(
        default_factory=list
    )

    report: dict[str, Any] = Field(
        default_factory=dict
    )

    def tool_event_summary(
        self,
    ) -> str:
        return (
            f"accepted={len(self.accepted_pages)} "
            f"pending={len(self.pending_followups)} "
            f"rejected={len(self.rejected_pages)} "
            f"errors={self.report.get('error_count', 0)}"
        )


class PageProcessingTool(BaseTool):
    """Process collected pages into accepted, pending, or rejected routes."""

    name = "page_processing"

    def __init__(
        self,
        provider: AIProvider,
        timeout_seconds: int = 90,
    ) -> None:
        self.provider = provider
        self.timeout_seconds = (
            timeout_seconds
        )

    def run(
        self,
        payload: BaseModel | dict[str, Any],
    ) -> PageProcessingOutput:
        data = (
            payload
            if isinstance(
                payload,
                PageProcessingInput,
            )
            else PageProcessingInput.model_validate(
                payload
            )
        )

        started_at = datetime.now(
            timezone.utc
        )

        processing_started = perf_counter()
        cleaning_started = perf_counter()
        processed_pages = [parse_collected_page(page) for page in data.pages]
        logger.info(
            "page_processing stage=cleaning elapsed_ms=%.1f pages=%s",
            (perf_counter() - cleaning_started) * 1000,
            len(processed_pages),
        )
        triage_started = perf_counter()
        triage = triage_pages(
            processed_pages,
            search_plan=data.search_plan,
            min_text_length=(
                data.min_text_length
            ),
        )
        logger.info(
            "page_processing stage=technical_triage elapsed_ms=%.1f pages=%s readable=%s recoverable=%s rejected=%s",
            (perf_counter() - triage_started) * 1000,
            len(processed_pages),
            len(triage.readable_pages),
            len(triage.recoverable_pages),
            len(triage.rejected_pages),
        )

        pages_ready_for_cleaning: list[
            PageContent
        ] = list(
            triage.readable_pages
        )

        pending_followups: list[
            PendingFollowup
        ] = []

        recovery_report: list[
            dict[str, Any]
        ] = []

        # Same-page deterministic recovery happens
        # before anything is handed to the Agent.
        for page in triage.recoverable_pages:
            route = (
                triage.recoverable_routes[
                    page.url
                ]
            )

            recovery_started = perf_counter()
            recovered_page, recovery = (
                recover_page(
                    page,
                    available_sources=(
                        route.recovery_sources
                    ),
                    min_recovered_chars=(
                        data.min_text_length
                    ),
                )
            )
            logger.info(
                "page_processing stage=recovery url=%s elapsed_ms=%.1f success=%s",
                page.url,
                (perf_counter() - recovery_started) * 1000,
                recovery.success,
            )

            recovery_report.append(
                {
                    "url": page.url,
                    "route": route.model_dump(),
                    "recovery": (
                        recovery.model_dump()
                    ),
                }
            )

            if recovery.success:
                pages_ready_for_cleaning.append(
                    recovered_page
                )
                continue

            pending_followups.append(
                _pending_followup_from_unrecovered_page(
                    page,
                    route,
                    recovery.model_dump(),
                )
            )

        cleaned_pages: list[
            AIPageInput
        ] = []

        cleaning_errors: list[
            dict[str, Any]
        ] = []

        for page in pages_ready_for_cleaning:
            try:
                cleaning_started = perf_counter()
                cleaned_pages.append(
                    build_ai_page_input(
                        page,
                        max_text_chars=(
                            data.max_text_chars
                        ),
                    )
                )
                logger.info(
                    "page_processing stage=cleaning url=%s elapsed_ms=%.1f success=true",
                    page.url,
                    (perf_counter() - cleaning_started) * 1000,
                )

            except Exception as exc:
                logger.info(
                    "page_processing stage=cleaning url=%s elapsed_ms=%.1f success=false",
                    page.url,
                    (perf_counter() - cleaning_started) * 1000,
                )
                cleaning_errors.append(
                    {
                        "url": page.url,
                        "title": page.title,
                        "reason": str(exc),
                    }
                )

                pending_followups.append(
                    _pending_followup_from_processing_error(
                        page,
                        reason=(
                            f"page_cleaning_failed: "
                            f"{exc}"
                        ),
                    )
                )

        classifier = PageSemanticClassifier(
            self.provider,
            timeout_seconds=(
                self.timeout_seconds
            ),
        )

        accepted_pages: list[
            AIPageInput
        ] = []

        classification_report: list[
            dict[str, Any]
        ] = []

        classification_errors: list[
            dict[str, Any]
        ] = []

        for page in cleaned_pages:
            classification_started = perf_counter()
            try:
                classification = (
                    classifier.classify(
                        page
                    )
                )

            except Exception as exc:
                logger.info(
                    "page_processing stage=semantic_classification url=%s elapsed_ms=%.1f success=false",
                    page.url,
                    (perf_counter() - classification_started) * 1000,
                )
                classification_errors.append(
                    {
                        "url": page.url,
                        "title": page.title,
                        "reason": str(exc),
                    }
                )

                pending_followups.append(
                    _pending_followup_from_classification_error(
                        page,
                        exc,
                    )
                )

                continue

            logger.info(
                "page_processing stage=semantic_classification url=%s elapsed_ms=%.1f success=true page_type=%s",
                page.url,
                (perf_counter() - classification_started) * 1000,
                classification.page_type,
            )

            classification_report.append(
                {
                    "url": page.url,
                    "title": page.title,
                    "source_name": (
                        page.source_name
                    ),
                    "classification": (
                        classification
                        .model_dump()
                    ),
                }
            )

            if (
                classification
                .is_job_detail_page
            ):
                accepted_pages.append(
                    page
                )

            else:
                pending_followups.append(
                    pending_followup_from_semantic_classification(
                        page,
                        classification,
                    )
                )

        finished_at = datetime.now(
            timezone.utc
        )

        report = {
            "started_at": (
                started_at.isoformat(
                    timespec="seconds"
                )
            ),
            "finished_at": (
                finished_at.isoformat(
                    timespec="seconds"
                )
            ),
            "input_page_count": len(
                data.pages
            ),
            "technical_readable_count": len(
                triage.readable_pages
            ),
            "technical_recoverable_count": len(
                triage.recoverable_pages
            ),
            "rejected_count": len(
                triage.rejected_pages
            ),
            "cleaned_page_count": len(
                cleaned_pages
            ),
            "accepted_page_count": len(
                accepted_pages
            ),
            "pending_followup_count": len(
                pending_followups
            ),
            "error_count": (
                len(cleaning_errors)
                + len(
                    classification_errors
                )
            ),
            "recovery": recovery_report,
            "classifications": (
                classification_report
            ),
            "cleaning_errors": (
                cleaning_errors
            ),
            "classification_errors": (
                classification_errors
            ),
            "elapsed_ms": round((perf_counter() - processing_started) * 1000, 1),
        }

        logger.info(
            "page_processing elapsed_ms=%.1f accepted=%s pending=%s rejected=%s errors=%s",
            report["elapsed_ms"],
            len(accepted_pages),
            len(pending_followups),
            len(triage.rejected_pages),
            report["error_count"],
        )
        for item in pending_followups:
            logger.info("page_processing pending url=%s reason=%s", item.url, "; ".join(item.reasons))
        for item in triage.rejected_pages:
            logger.info("page_processing rejected url=%s reason=%s", item.url, "; ".join(item.reasons))

        return PageProcessingOutput(
            accepted_pages=accepted_pages,
            pending_followups=(
                pending_followups
            ),
            rejected_pages=(
                triage.rejected_pages
            ),
            report=report,
        )


def _pending_followup_from_unrecovered_page(
    page: PageContent,
    route,
    recovery: dict[str, Any],
) -> PendingFollowup:
    """Create Agent-visible pending state only after deterministic recovery fails."""

    reason_text = " ".join(
        route.reasons
    ).lower()

    metadata = page.metadata or {}

    if (
        "html_body_empty"
        in reason_text
    ):
        pending_kind = (
            "javascript_rendered_or_hidden_content"
        )
        next_action = (
            "retry_with_browser_or_rendered_collection"
        )
        priority = 80

    elif (
        "auth"
        in reason_text
        or "login"
        in reason_text
    ):
        pending_kind = (
            "auth_or_interactive_required"
        )
        next_action = (
            "manual_review"
        )
        priority = 45

    elif (
        "fetch_error"
        in reason_text
        and any(
            marker in reason_text
            for marker in [
                "403",
                "429",
                "timeout",
                "timed out",
            ]
        )
    ):
        pending_kind = (
            "anti_bot_or_rate_limited"
        )
        next_action = (
            "retry_with_browser_or_rendered_collection"
        )
        priority = 65

    elif (
        "insufficient_visible_text"
        in reason_text
    ):
        pending_kind = (
            "insufficient_visible_text"
        )
        next_action = (
            "manual_review"
        )
        priority = 55

    else:
        pending_kind = (
            "unknown_but_potentially_relevant"
        )
        next_action = (
            "manual_review"
        )
        priority = 50

    final_url = metadata.get(
        "final_url"
    )

    links = metadata.get(
        "links",
        [],
    )

    normalized_links = (
        [
            link
            for link in links
            if isinstance(
                link,
                dict,
            )
        ]
        if isinstance(
            links,
            list,
        )
        else []
    )

    return PendingFollowup(
        url=page.url,
        final_url=(
            final_url
            if isinstance(
                final_url,
                str,
            )
            else None
        ),
        title=page.title,
        source_name=(
            page.source_name
        ),
        company_name=(
            _metadata_string(
                metadata,
                "company_name",
            )
        ),
        company_type=(
            _metadata_string(
                metadata,
                "company_type",
            )
        ),
        is_official=bool(
            metadata.get(
                "is_official",
                False,
            )
        ),
        pending_kind=pending_kind,
        reasons=route.reasons,
        evidence={
            "technical_route": (
                route.model_dump()
            ),
            "recovery": recovery,
        },
        suggested_next_action=(
            next_action
        ),
        priority=priority,
        links=normalized_links,
        stage="pre_extraction",
    )


def _pending_followup_from_processing_error(
    page: PageContent,
    reason: str,
) -> PendingFollowup:
    metadata = page.metadata or {}

    return PendingFollowup(
        url=page.url,
        final_url=(
            metadata.get("final_url")
            if isinstance(
                metadata.get(
                    "final_url"
                ),
                str,
            )
            else None
        ),
        title=page.title,
        source_name=(
            page.source_name
        ),
        company_name=(
            _metadata_string(
                metadata,
                "company_name",
            )
        ),
        company_type=(
            _metadata_string(
                metadata,
                "company_type",
            )
        ),
        is_official=bool(
            metadata.get(
                "is_official",
                False,
            )
        ),
        pending_kind=(
            "unknown_but_potentially_relevant"
        ),
        reasons=[reason],
        suggested_next_action=(
            "manual_review"
        ),
        priority=50,
        stage="pre_extraction",
    )


def _pending_followup_from_classification_error(
    page: AIPageInput,
    exc: Exception,
) -> PendingFollowup:
    return PendingFollowup(
        url=page.url,
        final_url=page.final_url,
        title=page.title,
        source_name=(
            page.source_name
            or page.url
        ),
        company_name=(
            page.source_company_name
        ),
        company_type=(
            page.company_type
        ),
        is_official=(
            page.is_official
        ),
        pending_kind=(
            "semantic_classification_failed"
        ),
        reasons=[
            f"semantic_classification_failed: {exc}"
        ],
        evidence={
            "text_length": len(
                page.visible_text
            )
        },
        suggested_next_action=(
            "manual_review"
        ),
        priority=55,
        links=[
            {
                "url": link.url,
                "text": link.text,
                "kind": link.kind,
            }
            for link
            in page.important_links
        ],
        stage="pre_extraction",
    )


def _metadata_string(
    metadata: dict,
    key: str,
) -> str | None:
    value = metadata.get(key)

    if (
        isinstance(value, str)
        and value.strip()
    ):
        return value

    return None
