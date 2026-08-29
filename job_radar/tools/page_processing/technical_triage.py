"""Deterministic technical triage before recovery and semantic classification."""

import re
from urllib.parse import parse_qs, urlparse

from pydantic import BaseModel, Field

from job_radar.tools.page_collection.models import PageContent
from job_radar.tools.page_processing.models import (
    PageTechnicalRoute,
    RecoverySource,
)
from job_radar.tools.web_search.models import SearchPlan


JD_SIGNAL_KEYWORDS = [
    "岗位职责",
    "任职要求",
    "职位描述",
    "工作地点",
    "招聘类别",
    "立即申请",
    "投递",
    "校园招聘",
    "校招",
    "应届",
    "招聘公告",
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
    "页面不存在",
    "页面未找到",
    "职位已下线",
    "岗位已下线",
    "招聘已结束",
    "已停止招聘",
    "no longer accepting applications",
    "job is no longer available",
    "position has been filled",
    "applications are closed",
]

AUTH_PAGE_KEYWORDS = [
    "登录",
    "注册",
    "login",
    "sign in",
]


class RejectedPage(BaseModel):
    """A page rejected by deterministic technical rules."""

    url: str
    source_name: str
    title: str

    reasons: list[str] = Field(default_factory=list)
    text_length: int = 0
    metadata: dict = Field(default_factory=dict)


class TechnicalTriageResult(BaseModel):
    """Technical triage results before deterministic recovery."""

    readable_pages: list[PageContent] = Field(default_factory=list)

    recoverable_pages: list[PageContent] = Field(default_factory=list)
    recoverable_routes: dict[str, PageTechnicalRoute] = Field(default_factory=dict)

    rejected_pages: list[RejectedPage] = Field(default_factory=list)


def triage_pages(
    pages: list[PageContent],
    search_plan: SearchPlan | None = None,
    min_text_length: int = 300,
) -> TechnicalTriageResult:
    """Classify pages as readable, recoverable, or rejected."""

    result = TechnicalTriageResult()

    for page in pages:
        route = route_page_technically(
            page,
            search_plan=search_plan,
            min_text_length=min_text_length,
        )

        if route.status == "rejected":
            result.rejected_pages.append(
                RejectedPage(
                    url=page.url,
                    source_name=page.source_name,
                    title=page.title,
                    reasons=route.reasons,
                    text_length=route.text_length,
                    metadata={
                        **page.metadata,
                        "technical_route": route.model_dump(),
                    },
                )
            )
            continue

        if route.status == "recoverable":
            result.recoverable_pages.append(page)
            result.recoverable_routes[page.url] = route
            continue

        result.readable_pages.append(page)

    return result


def route_page_technically(
    page: PageContent,
    search_plan: SearchPlan | None = None,
    min_text_length: int = 300,
) -> PageTechnicalRoute:
    """Return the deterministic technical route for one page."""

    rejection = rejection_reasons(
        page,
        search_plan=search_plan,
    )

    recovery_sources = detect_recovery_sources(page)

    fetch = page.fetch
    evidence = {
        "status_code": fetch.status_code if fetch.status_code is not None else page.metadata.get("status_code"),
        "final_url": fetch.final_url or page.metadata.get("final_url"),
        "content_type": fetch.content_type or page.metadata.get("content_type"),
        "fetch_method": fetch.fetch_method,
        "fetch_attempts": fetch.attempts,
        "fetch_error": fetch.error or page.metadata.get("fetch_error"),
        "text_length": len(page.text.strip()),
        "html_length": len(page.html or ""),
    }

    if rejection:
        return PageTechnicalRoute(
            status="rejected",
            reason_codes=[_reason_code(reason) for reason in rejection],
            reasons=rejection,
            text_length=len(page.text),
            html_length=len(page.html or ""),
            recovery_sources=recovery_sources,
            evidence=evidence,
        )

    pending = recovery_reasons(
        page,
        search_plan=search_plan,
        min_text_length=min_text_length,
    )

    if pending:
        return PageTechnicalRoute(
            status="recoverable",
            reason_codes=[_reason_code(reason) for reason in pending],
            reasons=pending,
            text_length=len(page.text),
            html_length=len(page.html or ""),
            recovery_sources=recovery_sources,
            evidence=evidence,
        )

    return PageTechnicalRoute(
        status="readable",
        text_length=len(page.text),
        html_length=len(page.html or ""),
        recovery_sources=recovery_sources,
        evidence=evidence,
    )


def rejection_reasons(
    page: PageContent,
    search_plan: SearchPlan | None = None,
) -> list[str]:
    """Return deterministic hard-rejection reasons."""

    reasons: list[str] = []

    status_code = page.fetch.status_code if page.fetch.status_code is not None else page.metadata.get("status_code")
    fetch_error = page.fetch.error or page.metadata.get("fetch_error")

    if fetch_error:
        reasons.append(f"fetch_error: {fetch_error}")

    if isinstance(status_code, int) and not 200 <= status_code < 400:
        reasons.append(f"bad_status_code: {status_code}")

    redirect_reason = _redirect_rejection_reason(page)
    if redirect_reason:
        reasons.append(redirect_reason)

    text = " ".join(
        [
            page.title,
            page.url,
            page.text,
        ]
    ).lower()

    jd_signals = _matches(text, JD_SIGNAL_KEYWORDS)

    plan_signals = (
        _plan_signal_matches(text, search_plan)
        if search_plan is not None
        else []
    )

    matched_rejection_keywords = _matches(
        text,
        STRONG_REJECTION_KEYWORDS,
    )

    if matched_rejection_keywords:
        reasons.append(
            "rejection_keywords: "
            + ", ".join(matched_rejection_keywords[:5])
        )

    if _is_auth_wall(
        page,
        text,
        jd_signals,
        plan_signals,
    ):
        matched_auth_keywords = _matches(
            text,
            AUTH_PAGE_KEYWORDS,
        )

        reasons.append(
            "auth_wall: "
            + ", ".join(matched_auth_keywords[:5])
        )

    return reasons


def recovery_reasons(
    page: PageContent,
    search_plan: SearchPlan | None = None,
    min_text_length: int = 300,
) -> list[str]:
    """Return reasons why same-page recovery should be attempted."""

    text_length = len(page.text.strip())

    if text_length >= min_text_length:
        return []

    reasons = [
        f"insufficient_visible_text: "
        f"{text_length} < {min_text_length}"
    ]

    recovery_sources = detect_recovery_sources(page)

    if recovery_sources:
        reasons.append(
            "recoverable_metadata_present: "
            + ", ".join(recovery_sources)
        )

    signals = summarize_page_signals(
        page,
        search_plan,
    )

    if (
        signals["jd_signals"]
        or signals["plan_signals"]
    ):
        reasons.append("candidate_signal_present")

    if len(page.html or "") > 1000 and text_length <= 30:
        reasons.append("html_body_empty")
    else:
        reasons.append("needs_manual_review")

    return reasons


def detect_recovery_sources(
    page: PageContent,
) -> list[RecoverySource]:
    """Detect deterministic recovery sources available in the same page."""

    html = page.html or ""
    sources: list[RecoverySource] = []

    if re.search(
        r"<script[^>]+type=[\"']application/ld\+json[\"']",
        html,
        re.I,
    ):
        sources.append("json_ld")

    if re.search(
        r"<meta[^>]+property=[\"']og:description[\"']",
        html,
        re.I,
    ):
        sources.append("og_description")

    if re.search(
        r"<meta[^>]+name=[\"']description[\"']",
        html,
        re.I,
    ):
        sources.append("meta_description")

    if re.search(
        r"(?:window\.|__INITIAL_STATE__|__NEXT_DATA__|"
        r"__APOLLO_STATE__|application/json)",
        html,
        re.I,
    ):
        sources.append("embedded_json")

    links = page.metadata.get("links", [])

    if isinstance(links, list) and links:
        sources.append("important_links")

    return list(dict.fromkeys(sources))


def summarize_page_signals(
    page: PageContent,
    search_plan: SearchPlan | None = None,
) -> dict[str, list[str]]:
    """Return deterministic diagnostic signals."""

    text = " ".join(
        [
            page.title,
            page.url,
            page.text,
        ]
    ).lower()

    return {
        "jd_signals": _matches(
            text,
            JD_SIGNAL_KEYWORDS,
        ),
        "plan_signals": (
            _plan_signal_matches(text, search_plan)
            if search_plan is not None
            else []
        ),
    }


def _matches(
    text: str,
    keywords: list[str],
) -> list[str]:
    return [
        keyword
        for keyword in keywords
        if keyword.lower() in text
    ]


def _plan_signal_matches(
    text: str,
    search_plan: SearchPlan | None,
) -> list[str]:
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
        "校招",
        "应届",
    ]

    return sorted(
        {
            candidate
            for candidate in candidates
            if candidate
            and candidate.lower() in text
        }
    )


def _redirect_rejection_reason(
    page: PageContent,
) -> str | None:
    final_url = page.metadata.get("final_url")

    if (
        not isinstance(final_url, str)
        or _canonical_url(final_url)
        == _canonical_url(page.url)
    ):
        return None

    final = urlparse(final_url)
    final_query = parse_qs(final.query)

    if "error" in final_query:
        return f"redirected_to_error_page: {final_url}"

    return None


def _reason_code(reason: str) -> str:
    lowered = reason.lower()

    if "404" in lowered or "not found" in lowered:
        return "not_found"

    if any(
        marker in lowered
        for marker in [
            "401",
            "403",
            "access denied",
            "forbidden",
        ]
    ):
        return "access_denied"

    prefix = reason.split(":", maxsplit=1)[0]

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

    return "needs_manual_review"


def _is_auth_wall(
    page: PageContent,
    text: str,
    jd_signals: list[str],
    plan_signals: list[str],
) -> bool:
    auth_keywords = _matches(
        text,
        AUTH_PAGE_KEYWORDS,
    )

    if not auth_keywords:
        return False

    title_and_url = (
        f"{page.title} {page.url}".lower()
    )

    if _matches(
        title_and_url,
        AUTH_PAGE_KEYWORDS,
    ):
        return True

    has_job_context = bool(
        jd_signals or plan_signals
    )

    return (
        not has_job_context
        and len(page.text) < 1200
    )


def _canonical_url(url: str) -> str:
    parsed = urlparse(url)

    return (
        parsed
        ._replace(
            fragment="",
            query="",
        )
        .geturl()
        .rstrip("/")
    )
