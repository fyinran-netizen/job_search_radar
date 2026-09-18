"""Small shared helpers for follow-up URL handling."""

from urllib.parse import urlsplit

from job_radar.tools.web_search.source_selection import normalize_url


def normalized_http_url(value: object) -> str | None:
    """Return a canonical HTTP(S) URL, or ``None`` for unusable input."""

    if not isinstance(value, str) or not value.strip():
        return None
    try:
        normalized = normalize_url(value)
        parts = urlsplit(normalized)
    except (TypeError, ValueError):
        return None
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return None
    return normalized


def normalized_url_set(values: set[str] | list[str]) -> set[str]:
    """Normalize URL values while ignoring malformed entries."""

    return {
        normalized
        for value in values
        if (normalized := normalized_http_url(value)) is not None
    }
