"""Stage 1 deterministic page routing before AI semantic classification."""

import re
from urllib.parse import parse_qs, urlparse

from pydantic import BaseModel, Field

from job_radar.models.page_triage import PageTechnicalRoute, PendingFollowup, RecoverySource
from job_radar.models.search import SearchPlan
from job_radar.models.tool import PageContent


JD_SIGNAL_KEYWORDS = [
    "\u5c97\u4f4d\u804c\u8d23",
    "\u4efb\u804c\u8981\u6c42",
    "\u804c\u4f4d\u63cf\u8ff0",
    "\u5de5\u4f5c\u5730\u70b9",
    "\u62db\u8058\u7c7b\u522b",
    "\u7acb\u5373\u7533\u8bf7",
    "\u6295\u9012",
    "\u6821\u56ed\u62db\u8058",
    "\u6821\u62db",
    "\u5e94\u5c4a",
    "\u62db\u8058\u516c\u544a",
    "responsibilities",
    "requirements",
    "qualifications",
    "location",
    "apply",
    "graduate program",
    "graduate programme",
    "graduate jobs",
    "early careers",
    "job description",
]

STRONG_REJECTION_KEYWORDS = [
    "404",
    "not found",
    "page unavailable",
    "page not found",
    "access denied",
    "forbidden",
    "\u9875\u9762\u4e0d\u5b58\u5728",
    "\u9875\u9762\u672a\u627e\u5230",
    "\u804c\u4f4d\u5df2\u4e0b\u7ebf",
    "\u5c97\u4f4d\u5df2\u4e0b\u7ebf",
    "\u62db\u8058\u5df2\u7ed3\u675f",
    "\u5df2\u505c\u6b62\u62db\u8058",
    "no longer accepting applications",
    "job is no longer available",
    "position has been filled",
    "applications are closed",
]

AUTH_PAGE_KEYWORDS = [
    "\u767b\u5f55",
    "\u6ce8\u518c",
    "login",
    "sign in",
]

class RejectedPage(BaseModel):
    """A fetched page rejected before AI extraction."""

    url: str
    source_name: str
    title: str
    reasons: list[str] = Field(default_factory=list)
    text_length: int = 0
    metadata: dict = Field(default_factory=dict)


class PendingPage(BaseModel):
    """A candidate page that may be useful but needs another collection method."""

    url: str
    source_name: str
    title: str
    reasons: list[str] = Field(default_factory=list)
    text_length: int = 0
    metadata: dict = Field(default_factory=dict)
    page: PageContent | None = None


class PageFilterResult(BaseModel):
    """Readable, pending, and rejected pages with reasons."""

    readable_pages: list[PageContent] = Field(default_factory=list)
    pending_pages: list[PendingPage] = Field(default_factory=list)
    rejected_pages: list[RejectedPage] = Field(default_factory=list)


def filter_pages(
    pages: list[PageContent],
    search_plan: SearchPlan | None = None,
    min_text_length: int = 300,
) -> PageFilterResult:
    """Route collected pages by technical readability before AI semantics."""

    result = PageFilterResult()
    for page in pages:
        route = route_page_technically(page, search_plan=search_plan, min_text_length=min_text_length)
        if route.status == "rejected":
            result.rejected_pages.append(
                RejectedPage(
                    url=page.url,
                    source_name=page.source_name,
                    title=page.title,
                    reasons=route.reasons,
                    text_length=route.text_length,
                    metadata={**page.metadata, "technical_route": route.model_dump()},
                )
            )
            continue
        if route.status == "recoverable":
            result.pending_pages.append(
                PendingPage(
                    url=page.url,
                    source_name=page.source_name,
                    title=page.title,
                    reasons=route.reasons,
                    text_length=route.text_length,
                    metadata={**page.metadata, "technical_route": route.model_dump()},
                    page=page,
                )
            )
            continue
        result.readable_pages.append(page)
    return result


def route_page_technically(
    page: PageContent,
    search_plan: SearchPlan | None = None,
    min_text_length: int = 300,
) -> PageTechnicalRoute:
    """Return the program-owned Stage 1 route for one fetched page."""

    rejection = rejection_reasons(page, search_plan=search_plan, min_text_length=min_text_length)
    recovery_sources = _recovery_sources(page)
    evidence = {
        "status_code": page.metadata.get("status_code"),
        "final_url": page.metadata.get("final_url"),
        "content_type": page.metadata.get("content_type"),
        "text_length": len(page.text.strip()),
        "html_length": len(page.html),
    }
    if rejection:
        return PageTechnicalRoute(
            status="rejected",
            reason_codes=[_reason_code(reason) for reason in rejection],
            reasons=rejection,
            text_length=len(page.text),
            html_length=len(page.html),
            recovery_sources=recovery_sources,
            evidence=evidence,
        )

    pending = pending_reasons(page, search_plan=search_plan, min_text_length=min_text_length)
    if pending:
        return PageTechnicalRoute(
            status="recoverable",
            reason_codes=[_reason_code(reason) for reason in pending],
            reasons=pending,
            text_length=len(page.text),
            html_length=len(page.html),
            recovery_sources=recovery_sources,
            evidence=evidence,
        )

    return PageTechnicalRoute(
        status="readable",
        text_length=len(page.text),
        html_length=len(page.html),
        recovery_sources=recovery_sources,
        evidence=evidence,
    )


def rejection_reasons(
    page: PageContent,
    search_plan: SearchPlan | None = None,
    min_text_length: int = 300,
) -> list[str]:
    """Return hard rejection reasons before AI extraction."""

    _ = min_text_length
    reasons: list[str] = []
    status_code = page.metadata.get("status_code")
    fetch_error = page.metadata.get("fetch_error")
    if fetch_error:
        reasons.append(f"fetch_error: {fetch_error}")
    if isinstance(status_code, int) and not 200 <= status_code < 400:
        reasons.append(f"bad_status_code: {status_code}")

    redirect_reason = _redirect_rejection_reason(page)
    if redirect_reason:
        reasons.append(redirect_reason)

    text = " ".join([page.title, page.url, page.text]).lower()
    jd_signals = _matches(text, JD_SIGNAL_KEYWORDS)
    plan_signals = _plan_signal_matches(text, search_plan) if search_plan else []

    matched_strong_rejection_keywords = _matches(text, STRONG_REJECTION_KEYWORDS)
    if matched_strong_rejection_keywords:
        reasons.append(f"rejection_keywords: {', '.join(matched_strong_rejection_keywords[:5])}")

    if _is_auth_wall(page, text, jd_signals, plan_signals):
        matched_auth_keywords = _matches(text, AUTH_PAGE_KEYWORDS)
        reasons.append(f"auth_wall: {', '.join(matched_auth_keywords[:5])}")

    return reasons


def pending_reasons(
    page: PageContent,
    search_plan: SearchPlan | None = None,
    min_text_length: int = 300,
) -> list[str]:
    """Return technical recovery reasons for pages that should not go to AI yet."""

    text_length = len(page.text.strip())
    if text_length >= min_text_length:
        return []

    reasons = [f"insufficient_visible_text: {text_length} < {min_text_length}"]
    recovery_sources = _recovery_sources(page)
    if recovery_sources:
        reasons.append("recoverable_metadata_present: " + ", ".join(recovery_sources))
    signals = summarize_page_signals(page, search_plan)
    if signals["jd_signals"] or signals["plan_signals"]:
        reasons.append("candidate_signal_present")
    if len(page.html) > 1000 and text_length <= 30:
        reasons.append("html_body_empty")
    else:
        reasons.append("needs_manual_review")
    return reasons


def pending_followup_from_pending_page(page: PendingPage) -> PendingFollowup:
    """Convert Stage 1 recoverable pages into agent-ready follow-up records."""

    reasons = page.reasons
    reason_text = " ".join(reasons).lower()
    route = page.metadata.get("technical_route", {}) if isinstance(page.metadata, dict) else {}
    recovery_sources = route.get("recovery_sources", []) if isinstance(route, dict) else []
    if "html_body_empty" in reason_text:
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
    elif "insufficient_visible_text" in reason_text and recovery_sources:
        pending_kind = "insufficient_visible_text"
        next_action = "manual_review"
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
            "recovery_sources": recovery_sources,
        },
        suggested_next_action=next_action,
        priority=priority,
        links=[],
        stage="collection",
    )


def summarize_page_signals(page: PageContent, search_plan: SearchPlan | None = None) -> dict[str, list[str]]:
    """Return matched signals for CLI diagnostics and logs."""

    text = " ".join([page.title, page.url, page.text]).lower()
    return {
        "jd_signals": _matches(text, JD_SIGNAL_KEYWORDS),
        "plan_signals": _plan_signal_matches(text, search_plan) if search_plan else [],
    }


def _matches(text: str, keywords: list[str]) -> list[str]:
    return [keyword for keyword in keywords if keyword.lower() in text]


def _plan_signal_matches(text: str, search_plan: SearchPlan | None) -> list[str]:
    if search_plan is None:
        return []
    candidates = [
        *search_plan.target_roles,
        *search_plan.locations,
        *search_plan.company_types,
        "graduate",
        "campus",
        "2026",
        "2027",
        "\u6821\u62db",
        "\u5e94\u5c4a",
    ]
    return sorted({candidate for candidate in candidates if candidate and candidate.lower() in text})


def _redirect_rejection_reason(page: PageContent) -> str | None:
    final_url = page.metadata.get("final_url")
    if not isinstance(final_url, str) or _canonical_url(final_url) == _canonical_url(page.url):
        return None

    final = urlparse(final_url)
    final_query = parse_qs(final.query)

    if "error" in final_query:
        return f"redirected_to_error_page: {final_url}"

    return None


def _recovery_sources(page: PageContent) -> list[RecoverySource]:
    html = page.html or ""
    sources: list[RecoverySource] = []
    if re.search(r"<script[^>]+type=[\"']application/ld\+json[\"']", html, re.I):
        sources.append("json_ld")
    if re.search(r"<meta[^>]+property=[\"']og:description[\"'][^>]+content=[\"'][^\"']+", html, re.I):
        sources.append("og_description")
    if re.search(r"<meta[^>]+name=[\"']description[\"'][^>]+content=[\"'][^\"']+", html, re.I):
        sources.append("meta_description")
    links = page.metadata.get("links", [])
    if isinstance(links, list) and links:
        sources.append("important_links")
    return sources


def _reason_code(reason: str):
    lowered = reason.lower()
    if "404" in lowered or "not found" in lowered:
        return "not_found"
    if "401" in lowered or "403" in lowered or "access denied" in lowered or "forbidden" in lowered:
        return "access_denied"
    prefix = reason.split(":", maxsplit=1)[0]
    if prefix == "likely_javascript_rendered_or_hidden_content":
        return "html_body_empty"
    if prefix in {
        "fetch_error",
        "bad_status_code",
        "redirected_to_error_page",
        "rejection_keywords",
        "auth_wall",
        "insufficient_visible_text",
        "html_body_empty",
        "recoverable_metadata_present",
        "needs_manual_review",
    }:
        return prefix
    if prefix == "candidate_signal_present":
        return "needs_manual_review"
    return "needs_manual_review"


def _is_auth_wall(
    page: PageContent,
    text: str,
    jd_signals: list[str],
    plan_signals: list[str],
) -> bool:
    auth_keywords = _matches(text, AUTH_PAGE_KEYWORDS)
    if not auth_keywords:
        return False

    title_and_url = f"{page.title} {page.url}".lower()
    if _matches(title_and_url, AUTH_PAGE_KEYWORDS):
        return True

    has_job_context = bool(jd_signals or plan_signals)
    return not has_job_context and len(page.text) < 1200


def _canonical_url(url: str) -> str:
    parsed = urlparse(url)
    return parsed._replace(fragment="", query="").geturl().rstrip("/")


def _metadata_string(metadata: dict, key: str) -> str | None:
    value = metadata.get(key)
    return value if isinstance(value, str) and value.strip() else None
