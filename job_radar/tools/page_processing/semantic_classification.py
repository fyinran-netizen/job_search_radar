"""AI semantic classification after deterministic page processing."""

from typing import Literal

from pydantic import BaseModel, Field

from job_radar.infra.llm.base import AIProvider
from job_radar.infra.llm.prompt_builder import build_json_prompt
from job_radar.infra.llm.prompt_loader import load_skill
from job_radar.infra.llm.structured_output import validate_model
from job_radar.tools.job_extraction.models import AIPageInput
from job_radar.tools.page_processing.models import (
    PageSemanticType,
    PendingFollowup,
    SuggestedNextAction,
)


class PageSemanticClassification(BaseModel):
    """Semantic label and bounded routing hint for one processed page."""

    page_type: PageSemanticType

    suggested_next_action: SuggestedNextAction = (
        "manual_review"
    )

    reasons: list[str] = Field(
        default_factory=list
    )

    evidence: list[str] = Field(
        default_factory=list
    )

    confidence: Literal[
        "high",
        "medium",
        "low",
    ] = "low"

    @property
    def is_job_detail_page(
        self,
    ) -> bool:
        return (
            self.page_type
            == "job_detail"
        )


class PageSemanticClassifier:
    """Classify processed pages by business-semantic page type."""

    def __init__(
        self,
        provider: AIProvider,
        skill_name: str = "page-jd-classification",
        max_text_chars: int = 6000,
        timeout_seconds: int = 90,
    ) -> None:
        self.provider = provider
        self.skill_name = skill_name
        self.max_text_chars = max_text_chars
        self.timeout_seconds = (
            timeout_seconds
        )

    def classify(
        self,
        page: AIPageInput,
    ) -> PageSemanticClassification:
        """Return only semantic type and a bounded routing hint."""

        skill = load_skill(
            self.skill_name
        )

        prompt = build_json_prompt(
            skill,
            {
                "page": {
                    "title": page.title,
                    "visible_text": (
                        page.visible_text[
                            : self.max_text_chars
                        ]
                    ),
                    "important_links": [
                        link.model_dump()
                        for link
                        in page.important_links
                    ],
                },
                "allowed_page_types": [
                    "job_detail",
                    "job_listing",
                    "apply_portal",
                    "recruitment_program",
                    "career_home",
                    "role_list_without_jd",
                    "document_or_brochure",
                    "access_or_interactive_page",
                    "irrelevant",
                    "uncertain",
                ],
                "routing_rule": (
                    "Classify only the semantic type of the current page. "
                    "Do not assume child pages have been visited. "
                    "Use page_type=job_detail and "
                    "suggested_next_action=extract_jobs only when the "
                    "current page contains concrete job-detail content "
                    "ready for extraction."
                ),
            },
            output_model=(
                PageSemanticClassification
            ),
        )

        data = self.provider.generate_json(
            prompt,
            timeout_seconds=(
                self.timeout_seconds
            ),
        )

        classification = validate_model(
            data,
            PageSemanticClassification,
        )

        return _normalize_classification(
            classification
        )


def pending_followup_from_semantic_classification(
    page: AIPageInput,
    classification: PageSemanticClassification,
) -> PendingFollowup:
    """Convert a non-job-detail classification into Agent-visible pending state."""

    page_type = (
        classification.page_type
    )

    return PendingFollowup(
        url=page.url,
        final_url=page.final_url,
        title=page.title,
        source_name=(
            page.source_name
            or _source_name_from_url(
                page.url
            )
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
            _pending_kind_from_page_type(
                page,
                classification,
            )
        ),
        reasons=(
            classification.reasons
            or [
                f"page routed as "
                f"{page_type}"
            ]
        ),
        evidence={
            "classifier": (
                classification
                .model_dump()
            ),
            "text_length": len(
                page.visible_text
            ),
        },
        suggested_next_action=(
            _next_action_for_page_type(
                page_type,
                classification,
            )
        ),
        priority=(
            _priority_from_page_type(
                page_type
            )
        ),
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


def _normalize_classification(
    classification: PageSemanticClassification,
) -> PageSemanticClassification:
    """Enforce deterministic consistency between page type and next action."""

    if (
        classification.page_type
        == "job_detail"
    ):
        return classification.model_copy(
            update={
                "suggested_next_action": (
                    "extract_jobs"
                )
            }
        )

    if (
        classification
        .suggested_next_action
        == "extract_jobs"
    ):
        return classification.model_copy(
            update={
                "suggested_next_action": (
                    "manual_review"
                )
            }
        )

    return classification


def _pending_kind_from_page_type(
    page: AIPageInput,
    classification: PageSemanticClassification,
) -> str:
    page_type = (
        classification.page_type
    )

    if page_type == "job_listing":
        return "job_listing_page"

    if page_type == "apply_portal":
        return (
            "official_apply_portal"
            if page.is_official
            else "apply_portal"
        )

    if page_type == "document_or_brochure":
        return "document_or_brochure"

    if page_type == "access_or_interactive_page":
        return "auth_or_interactive_required"

    return page_type


def _next_action_for_page_type(
    page_type: PageSemanticType,
    classification: PageSemanticClassification,
) -> SuggestedNextAction:
    """Return a bounded routing hint without executing the action."""

    if page_type == "job_listing":
        return "fetch_detail_links"

    if page_type == "role_list_without_jd":
        return "find_detail_pages_for_role_titles"

    if page_type in {
        "career_home",
        "recruitment_program",
        "apply_portal",
    }:
        return "open_portal_and_find_job_detail_pages"

    if page_type == "access_or_interactive_page":
        return "retry_with_browser_or_rendered_collection"

    if page_type == "irrelevant":
        return "skip_until_more_context"

    if page_type == "uncertain":
        return "manual_review"

    return (
        classification
        .suggested_next_action
    )


def _priority_from_page_type(
    page_type: str,
) -> int:
    if page_type in {
        "job_listing",
        "apply_portal",
        "role_list_without_jd",
    }:
        return 80

    if page_type == "recruitment_program":
        return 75

    if page_type in {
        "career_home",
        "document_or_brochure",
        "access_or_interactive_page",
    }:
        return 60

    if page_type == "irrelevant":
        return 20

    return 50


def _source_name_from_url(
    url: str,
) -> str:
    parts = url.split(
        "/",
        3,
    )

    if (
        "://" in url
        and len(parts) > 2
    ):
        return parts[2]

    return url


# Temporary compatibility aliases.
PageJDClassification = (
    PageSemanticClassification
)

PageJDClassifier = (
    PageSemanticClassifier
)
