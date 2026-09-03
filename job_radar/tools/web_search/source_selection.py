"""Deterministic candidate-source normalization and selection."""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from job_radar.tools.web_search.models import CandidateSource

_TRACKING_KEYS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "gclid"}
_AGGREGATE_MARKERS = ("search", "job-search", "jobsearch", "careers", "opportunities", "listing")


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    scheme, host = parts.scheme.lower(), (parts.hostname or "").lower()
    port = parts.port
    netloc = host if not port or (scheme == "http" and port == 80) or (scheme == "https" and port == 443) else f"{host}:{port}"
    path = parts.path.rstrip("/") or "/"
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if k.lower() not in _TRACKING_KEYS])
    return urlunsplit((scheme, netloc, path, query, ""))


def select_sources(
    sources: list[CandidateSource], *, previous_urls: set[str] | None = None,
    min_relevance_score: int = 70, max_sources: int = 10,
) -> list[CandidateSource]:
    """Normalize, deduplicate, rank and bound candidate sources."""
    seen = {normalize_url(url) for url in (previous_urls or set())}
    by_url: dict[str, CandidateSource] = {}
    for original in sources:
        url = normalize_url(original.url)
        if not url or url in seen:
            continue
        source = original.model_copy(update={"url": url})
        if source.relevance_score < min_relevance_score:
            continue
        path = urlsplit(url).path.casefold()
        detail = any(token in path for token in ("/job/", "/jobs/", "/position/", "/detail", "/vacancy"))
        if any(marker in path for marker in _AGGREGATE_MARKERS) and not detail:
            source = source.model_copy(update={"relevance_score": max(0, source.relevance_score - 15)})
            if source.relevance_score < min_relevance_score:
                continue
        host = (urlsplit(url).hostname or "").casefold()
        official = source.is_official or any(marker in host for marker in ("career", "jobs", "workday", "greenhouse", "lever"))
        if official:
            source = source.model_copy(update={"is_official": True, "relevance_score": min(100, source.relevance_score + 5)})
        current = by_url.get(url)
        if current is None or (source.is_official, source.relevance_score) > (current.is_official, current.relevance_score):
            by_url[url] = source
    return sorted(by_url.values(), key=lambda item: (item.is_official, item.relevance_score), reverse=True)[:max_sources]
