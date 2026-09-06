"""Deterministic candidate-source normalization and selection."""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from job_radar.tools.web_search.models import CandidateSource

_TRACKING_KEYS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "gclid"}


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
    """Normalize, deduplicate, and bound candidate sources.

    ``min_relevance_score`` remains accepted for call-site compatibility, but
    search scores are observational metadata and never affect selection.
    """
    del min_relevance_score
    seen = {normalize_url(url) for url in (previous_urls or set())}
    by_url: dict[str, CandidateSource] = {}
    for original in sources:
        url = normalize_url(original.url)
        if not url or url in seen:
            continue
        source = original.model_copy(update={"url": url})
        if url not in by_url:
            by_url[url] = source
    return list(by_url.values())[:max_sources]
