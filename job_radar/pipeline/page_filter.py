"""Deterministic page filtering before AI job extraction."""

from urllib.parse import parse_qs, urlparse

from pydantic import BaseModel, Field

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
    """Accepted, pending, and rejected pages with reasons."""

    accepted_pages: list[PageContent] = Field(default_factory=list)
    pending_pages: list[PendingPage] = Field(default_factory=list)
    rejected_pages: list[RejectedPage] = Field(default_factory=list)


def filter_pages(
    pages: list[PageContent],
    search_plan: SearchPlan | None = None,
    min_text_length: int = 300,
) -> PageFilterResult:
    """Classify collected pages before AI extraction."""

    result = PageFilterResult()
    for page in pages:
        reasons = rejection_reasons(page, search_plan=search_plan, min_text_length=min_text_length)
        if reasons:
            result.rejected_pages.append(
                RejectedPage(
                    url=page.url,
                    source_name=page.source_name,
                    title=page.title,
                    reasons=reasons,
                    text_length=len(page.text),
                    metadata=page.metadata,
                )
            )
            continue
        pending = pending_reasons(page, search_plan=search_plan, min_text_length=min_text_length)
        if pending:
            result.pending_pages.append(
                PendingPage(
                    url=page.url,
                    source_name=page.source_name,
                    title=page.title,
                    reasons=pending,
                    text_length=len(page.text),
                    metadata=page.metadata,
                    page=page,
                )
            )
            continue
        result.accepted_pages.append(page)
    return result


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
    """Return reasons for pages that should be kept but not extracted yet."""

    text_length = len(page.text.strip())
    if text_length >= min_text_length:
        return []

    reasons = [f"insufficient_visible_text: {text_length} < {min_text_length}"]
    signals = summarize_page_signals(page, search_plan)
    if signals["jd_signals"] or signals["plan_signals"]:
        reasons.append("candidate_signal_present")
    if len(page.html) > 1000 and text_length <= 30:
        reasons.append("likely_javascript_rendered_or_hidden_content")
    else:
        reasons.append("needs_manual_review")
    return reasons


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
