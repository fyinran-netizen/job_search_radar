"""Deterministic follow-up checks after job extraction."""

from collections import Counter
from urllib.parse import urlparse

from job_radar.ai.tasks.job_extraction import AIPageInput
from job_radar.models.job import RawJobRecord
from job_radar.models.page_triage import PendingFollowup


def triage_extracted_page(page_input: AIPageInput, records: list[RawJobRecord]) -> PendingFollowup | None:
    """Return pending follow-up when extraction produced low-detail records."""

    if not records:
        return _pending_from_page_input(
            page_input,
            pending_kind="no_jobs_extracted",
            reasons=["JD-classified page produced no job records after extraction"],
            evidence={"extracted_job_count": 0},
            suggested_next_action="manual_review",
            priority=60,
        )

    missing_description = sum(not record.description for record in records)
    missing_requirements = sum(not record.requirements for record in records)
    missing_location = sum(not record.location for record in records)
    unique_apply_urls = sorted({record.apply_url for record in records if record.apply_url})
    role_titles = [record.title for record in records if record.title]
    title_counter = Counter(role_titles)
    sparse_records = sum(
        not record.description and not record.requirements
        for record in records
    )
    sparse_ratio = sparse_records / len(records)
    evidence = {
        "extracted_job_count": len(records),
        "missing_description_count": missing_description,
        "missing_requirements_count": missing_requirements,
        "missing_location_count": missing_location,
        "unique_apply_url_count": len(unique_apply_urls),
        "shared_apply_urls": unique_apply_urls[:5],
        "sparse_record_ratio": round(sparse_ratio, 3),
        "duplicate_title_count": sum(count - 1 for count in title_counter.values() if count > 1),
    }

    if len(records) >= 10 and sparse_ratio >= 0.75:
        return _pending_from_page_input(
            page_input,
            pending_kind="role_list_without_jd",
            reasons=[
                "many role titles were extracted from one page",
                "most extracted records lack description and requirements",
            ],
            evidence=evidence,
            suggested_next_action="find_detail_pages_for_role_titles",
            priority=80,
            role_titles=role_titles[:100],
        )

    if len(records) >= 2 and sparse_ratio >= 0.8 and (unique_apply_urls or page_input.important_links):
        return _pending_from_page_input(
            page_input,
            pending_kind="role_list_without_jd",
            reasons=[
                "multiple role titles were extracted from one page",
                "extracted records lack concrete description and requirements",
                "page likely needs detail pages or an interactive apply portal before matching",
            ],
            evidence=evidence,
            suggested_next_action="find_detail_pages_for_role_titles",
            priority=80,
            role_titles=role_titles[:100],
        )

    if len(records) >= 10 and len(unique_apply_urls) <= 1 and missing_description >= len(records) * 0.5:
        return _pending_from_page_input(
            page_input,
            pending_kind="needs_detail_page",
            reasons=["many jobs share the same apply URL and need detail pages before matching"],
            evidence=evidence,
            suggested_next_action="find_detail_pages_for_role_titles",
            priority=75,
            role_titles=role_titles[:100],
        )

    return None


def _pending_from_page_input(
    page_input: AIPageInput,
    pending_kind,
    reasons: list[str],
    evidence: dict,
    suggested_next_action,
    priority: int,
    role_titles: list[str] | None = None,
) -> PendingFollowup:
    return PendingFollowup(
        url=page_input.url,
        final_url=page_input.final_url,
        title=page_input.title,
        source_name=page_input.source_name or _source_name_from_url(page_input.url),
        company_name=page_input.source_company_name,
        company_type=page_input.company_type,
        is_official=page_input.is_official,
        pending_kind=pending_kind,
        reasons=reasons,
        evidence=evidence,
        suggested_next_action=suggested_next_action,
        priority=priority,
        role_titles=role_titles or [],
        links=[
            {"url": link.url, "text": link.text, "kind": link.kind}
            for link in page_input.important_links
        ],
        stage="post_extraction",
    )


def _source_name_from_url(url: str) -> str:
    parsed = urlparse(url)
    return parsed.netloc or url
