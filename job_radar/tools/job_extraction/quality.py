"""Quality and completeness checks for extraction results."""

from collections import Counter
from urllib.parse import urlparse

from job_radar.tools.page_analysis.models import AIPageInput
from job_radar.tools.job_extraction.models import RawJobRecord

from job_radar.tools.page_analysis.models import (
    PendingFollowup,
)


class ExtractionReliabilityError(
    RuntimeError
):
    """Raised when expected extraction coverage is missing."""


def validate_extracted_page_coverage(
    records: list[RawJobRecord],
    expected_source_urls: list[str],
) -> None:
    """Require every expected page to produce at least one record."""

    represented_urls = {
        record.source_url
        for record in records
        if record.source_url
    }

    missing_urls = [
        url
        for url in expected_source_urls
        if url not in represented_urls
    ]

    if missing_urls:
        raise ExtractionReliabilityError(
            "No jobs were extracted from "
            "expected JD page(s): "
            + ", ".join(missing_urls)
        )


def triage_extracted_page(
    page: AIPageInput,
    records: list[RawJobRecord],
) -> PendingFollowup | None:
    """Detect extraction results that require more page discovery."""

    if not records:
        return _pending(
            page,
            pending_kind=(
                "no_jobs_extracted"
            ),
            reasons=[
                "JD-classified page produced "
                "no job records after extraction"
            ],
            evidence={
                "extracted_job_count": 0
            },
            suggested_next_action=(
                "manual_review"
            ),
            priority=60,
        )

    if any(not record.company_name for record in records):
        return _pending(
            page,
            pending_kind="uncertain",
            reasons=[
                "primary JD does not disclose an explicit employer name",
                "company_name must be resolved before validation and persistence",
            ],
            evidence={
                "extracted_job_count": len(records),
                "missing_company_name_count": sum(
                    not record.company_name for record in records
                ),
            },
            suggested_next_action="manual_review",
            priority=70,
        )

    missing_description = sum(
        not record.description
        for record in records
    )

    missing_requirements = sum(
        not record.requirements
        for record in records
    )

    missing_location = sum(
        not record.locations
        for record in records
    )

    unique_apply_urls = sorted(
        {
            record.apply_url
            for record in records
            if record.apply_url
        }
    )

    role_titles = [
        record.title
        for record in records
        if record.title
    ]

    title_counter = Counter(
        role_titles
    )

    sparse_records = sum(
        (
            not record.description
            and not record.requirements
        )
        for record in records
    )

    sparse_ratio = (
        sparse_records
        / len(records)
    )

    evidence = {
        "extracted_job_count": (
            len(records)
        ),
        "missing_description_count": (
            missing_description
        ),
        "missing_requirements_count": (
            missing_requirements
        ),
        "missing_location_count": (
            missing_location
        ),
        "unique_apply_url_count": (
            len(unique_apply_urls)
        ),
        "shared_apply_urls": (
            unique_apply_urls[:5]
        ),
        "sparse_record_ratio": (
            round(
                sparse_ratio,
                3,
            )
        ),
        "duplicate_title_count": sum(
            count - 1
            for count
            in title_counter.values()
            if count > 1
        ),
    }

    if (
        len(records) >= 10
        and sparse_ratio >= 0.75
    ):
        return _pending(
            page,
            pending_kind=(
                "role_list_without_jd"
            ),
            reasons=[
                "many role titles were "
                "extracted from one page",
                "most extracted records "
                "lack description and requirements",
            ],
            evidence=evidence,
            suggested_next_action=(
                "find_detail_pages_for_role_titles"
            ),
            priority=80,
            role_titles=role_titles[:100],
        )

    if (
        len(records) >= 2
        and sparse_ratio >= 0.8
        and (
            unique_apply_urls
            or page.important_links
        )
    ):
        return _pending(
            page,
            pending_kind=(
                "role_list_without_jd"
            ),
            reasons=[
                "multiple role titles were "
                "extracted from one page",
                "records lack concrete "
                "description and requirements",
                "detail pages or an interactive "
                "portal are likely required",
            ],
            evidence=evidence,
            suggested_next_action=(
                "find_detail_pages_for_role_titles"
            ),
            priority=80,
            role_titles=role_titles[:100],
        )

    if (
        len(records) >= 10
        and len(unique_apply_urls) <= 1
        and missing_description
        >= len(records) * 0.5
    ):
        return _pending(
            page,
            pending_kind=(
                "needs_detail_page"
            ),
            reasons=[
                "many jobs share the same "
                "apply URL and appear to need "
                "individual detail pages"
            ],
            evidence=evidence,
            suggested_next_action=(
                "find_detail_pages_for_role_titles"
            ),
            priority=75,
            role_titles=role_titles[:100],
        )

    return None


def _pending(
    page: AIPageInput,
    pending_kind,
    reasons: list[str],
    evidence: dict,
    suggested_next_action,
    priority: int,
    role_titles: list[str] | None = None,
) -> PendingFollowup:

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
            pending_kind
        ),
        reasons=reasons,
        evidence=evidence,
        suggested_next_action=(
            suggested_next_action
        ),
        priority=priority,
        role_titles=(
            role_titles or []
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
        stage="post_extraction",
    )


def _source_name_from_url(
    url: str,
) -> str:

    parsed = urlparse(url)

    return (
        parsed.netloc
        or url
    )
