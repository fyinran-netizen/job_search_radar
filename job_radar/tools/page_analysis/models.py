"""Shared models for deterministic and semantic page analysis."""

from typing import Any, Literal

from pydantic import BaseModel, Field


PageSemanticType = Literal[
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
]

PendingKind = Literal[
    "official_apply_portal",
    "apply_portal",
    "job_listing_page",
    "job_listing",
    "recruitment_program",
    "career_home",
    "role_list_without_jd",
    "campus_brochure_or_notice",
    "document_or_brochure",
    "access_or_interactive_page",
    "irrelevant",
    "uncertain",
    "javascript_rendered_or_hidden_content",
    "auth_or_interactive_required",
    "insufficient_visible_text",
    "needs_detail_page",
    "not_job_detail_page",
    "anti_bot_or_rate_limited",
    "semantic_classification_failed",
    "no_jobs_extracted",
    "unknown_but_potentially_relevant",
]

SuggestedNextAction = Literal[
    "extract_jobs",
    "open_portal_and_find_job_detail_pages",
    "fetch_detail_links",
    "find_detail_pages_for_role_titles",
    "retry_with_browser_or_rendered_collection",
    "manual_review",
    "skip_until_more_context",
]


class PendingFollowup(BaseModel):
    """A useful but unresolved page for a later Agent decision."""

    url: str
    final_url: str | None = None
    title: str
    source_name: str

    company_name: str | None = None
    company_type: str | None = None
    is_official: bool = False

    pending_kind: PendingKind

    reasons: list[str] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)

    suggested_next_action: SuggestedNextAction
    priority: int = Field(default=50, ge=0, le=100)

    role_titles: list[str] = Field(default_factory=list)
    links: list[dict[str, str]] = Field(default_factory=list)

    stage: Literal[
        "collection",
        "pre_extraction",
        "post_extraction",
    ] = "pre_extraction"
