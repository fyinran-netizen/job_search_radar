"""Canonical URL utilities shared by discovery and work admission."""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


_TRACKING_KEYS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "gclid"}


def normalize_url(url: str) -> str:
    """Return a stable URL form for identity and deduplication."""

    parts = urlsplit(url.strip())
    scheme, host = parts.scheme.lower(), (parts.hostname or "").lower()
    port = parts.port
    netloc = host if not port or (scheme == "http" and port == 80) or (scheme == "https" and port == 443) else f"{host}:{port}"
    path = parts.path.rstrip("/") or "/"
    query = urlencode([(key, value) for key, value in parse_qsl(parts.query) if key.lower() not in _TRACKING_KEYS])
    return urlunsplit((scheme, netloc, path, query, ""))
