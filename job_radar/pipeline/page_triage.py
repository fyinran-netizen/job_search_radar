"""Deterministic page triage for accepted, rejected, and pending queues."""

import re
from collections import Counter
from urllib.parse import urlparse

from job_radar.ai.tasks.job_extraction import AIPageInput
from job_radar.models.job import RawJobRecord
from job_radar.models.page_triage import PendingFollowup
from job_radar.models.tool import PageContent
from job_radar.pipeline.page_filter import PendingPage

APPLY_PORTAL_TERMS = [
    "立即投递",
    "投递",
    "应届生招聘",
    "实习生招聘",
    "校招项目",
    "登录/注册",
    "apply now",
    "apply",
    "search jobs",
]

DETAIL_TERMS = [
    "岗位职责",
    "任职要求",
    "职位描述",
    "工作职责",
    "工作内容",
    "requirements",
    "responsibilities",
    "qualifications",
]

LISTING_TERMS = [
    "招聘职位",
    "职位列表",
    "校招职位",
    "job openings",
    "open positions",
]


def triage_page_before_extraction(page: PageContent) -> PendingFollowup | None:
    """Return pending follow-up when a page is useful but not ready for extraction."""

    text = " ".join([page.title, page.text])
    lowered = text.lower()
    detail_hits = _matches(lowered, DETAIL_TERMS)
    portal_hits = _matches(lowered, APPLY_PORTAL_TERMS)
    listing_hits = _matches(lowered, LISTING_TERMS)
    links = _metadata_links(page)
    evidence = {
        "text_length": len(page.text),
        "detail_signal_count": len(detail_hits),
        "portal_signal_count": len(portal_hits),
        "listing_signal_count": len(listing_hits),
        "link_count": len(links),
        "matched_terms": sorted(set([*portal_hits, *listing_hits])),
    }

    if portal_hits and not detail_hits and _looks_like_official_or_portal(page):
        return _pending_from_page(
            page,
            pending_kind="official_apply_portal",
            reasons=["page looks like a useful apply portal but does not expose concrete job descriptions"],
            evidence=evidence,
            suggested_next_action="open_portal_and_find_job_detail_pages",
            priority=85 if page.metadata.get("is_official") else 70,
            stage="pre_extraction",
        )

    if listing_hits and not detail_hits:
        return _pending_from_page(
            page,
            pending_kind="job_listing_page",
            reasons=["page looks like a listing and likely needs detail-page links before extraction"],
            evidence=evidence,
            suggested_next_action="fetch_detail_links",
            priority=75,
            stage="pre_extraction",
        )

    return None


def pending_followup_from_pending_page(page: PendingPage) -> PendingFollowup:
    """Convert existing filter pending records into agent-ready follow-up records."""

    reasons = page.reasons
    reason_text = " ".join(reasons).lower()
    if "javascript" in reason_text or "hidden_content" in reason_text:
        pending_kind = "javascript_rendered_or_hidden_content"
        next_action = "retry_with_browser_or_rendered_collection"
        priority = 80
    elif "auth" in reason_text or "login" in reason_text:
        pending_kind = "auth_or_interactive_required"
        next_action = "manual_review"
        priority = 45
    elif "fetch_error" in reason_text and any(marker in reason_text for marker in ["403", "429", "timeout", "timed out"]):
        pending_kind = "anti_bot_or_rate_limited"
        next_action = "retry_with_browser_or_rendered_collection"
        priority = 65
    elif "insufficient_visible_text" in reason_text:
        pending_kind = "insufficient_visible_text"
        next_action = "manual_review"
        priority = 55
    else:
        pending_kind = "unknown_but_potentially_relevant"
        next_action = "manual_review"
        priority = 50

    metadata = page.metadata or {}
    final_url = metadata.get("final_url")
    return PendingFollowup(
        url=page.url,
        final_url=final_url if isinstance(final_url, str) else None,
        title=page.title,
        source_name=page.source_name,
        company_name=_metadata_string(metadata, "company_name"),
        company_type=_metadata_string(metadata, "company_type"),
        is_official=bool(metadata.get("is_official", False)),
        pending_kind=pending_kind,
        reasons=reasons,
        evidence={
            "text_length": page.text_length,
            "filter_metadata": metadata,
        },
        suggested_next_action=next_action,
        priority=priority,
        links=[],
        stage="collection",
    )


def triage_extracted_page(page_input: AIPageInput, records: list[RawJobRecord]) -> PendingFollowup | None:
    """Return pending follow-up when extraction produced low-detail records."""

    if not records:
        return _pending_from_page_input(
            page_input,
            pending_kind="no_jobs_extracted",
            reasons=["accepted page produced no job records after extraction"],
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


def _pending_from_page(
    page: PageContent,
    pending_kind,
    reasons: list[str],
    evidence: dict,
    suggested_next_action,
    priority: int,
    stage,
) -> PendingFollowup:
    metadata = page.metadata or {}
    final_url = metadata.get("final_url")
    return PendingFollowup(
        url=page.url,
        final_url=final_url if isinstance(final_url, str) else None,
        title=page.title,
        source_name=page.source_name,
        company_name=_metadata_string(metadata, "company_name"),
        company_type=_metadata_string(metadata, "company_type"),
        is_official=bool(metadata.get("is_official", False)),
        pending_kind=pending_kind,
        reasons=reasons,
        evidence=evidence,
        suggested_next_action=suggested_next_action,
        priority=priority,
        links=_metadata_links(page),
        stage=stage,
    )


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


def _matches(text: str, terms: list[str]) -> list[str]:
    return [term for term in terms if term.lower() in text]


def _looks_like_official_or_portal(page: PageContent) -> bool:
    if page.metadata.get("is_official"):
        return True
    parsed = urlparse(page.url)
    return any(marker in parsed.netloc.lower() for marker in ["career", "campus", "recruit", "zhaopin"])


def _metadata_string(metadata: dict, key: str) -> str | None:
    value = metadata.get(key)
    return value if isinstance(value, str) and value.strip() else None


def _metadata_links(page: PageContent) -> list[dict[str, str]]:
    links = page.metadata.get("links", [])
    if not isinstance(links, list):
        return []
    normalized = []
    for link in links[:20]:
        if not isinstance(link, dict):
            continue
        url = link.get("href") or link.get("url")
        text = link.get("text", "")
        if isinstance(url, str) and url:
            normalized.append({"url": url, "text": str(text)})
    return normalized


def _source_name_from_url(url: str) -> str:
    parsed = urlparse(url)
    return parsed.netloc or url
