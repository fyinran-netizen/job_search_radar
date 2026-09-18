"""Bounded HTTP/file transport. This module does not decode or parse pages."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time
from typing import Mapping
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, url2pathname, urlopen


@dataclass(frozen=True)
class HttpResponse:
    raw_bytes: bytes
    status_code: int | None
    final_url: str | None
    headers: Mapping[str, str]
    attempts: int
    fetch_method: str = "http"


class HttpTransport:
    """Fetch raw bytes, retry transient failures, and preserve HTTP facts."""

    def __init__(self, timeout_seconds: int = 20, retries: int = 2, max_response_bytes: int = 2_000_000) -> None:
        self.timeout_seconds = timeout_seconds
        self.retries = max(0, retries)
        self.max_response_bytes = max_response_bytes

    def fetch(self, url: str) -> HttpResponse:
        parsed = urlparse(url)
        if parsed.scheme == "file":
            raw = Path(url2pathname(parsed.path)).read_bytes()
            if len(raw) > self.max_response_bytes:
                raise ValueError(f"response exceeds limit: {len(raw)} bytes")
            return HttpResponse(raw, 200, url, {"Content-Type": "text/html"}, 1, "file")

        last_error: Exception | None = None
        for attempt in range(1, self.retries + 2):
            try:
                request = Request(
                    url,
                    headers={
                        "User-Agent": "JobRadar/0.1 local research tool",
                        "Accept": "text/html,application/xhtml+xml,application/json;q=0.8,*/*;q=0.1",
                    },
                )
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    raw = response.read(self.max_response_bytes + 1)
                    if len(raw) > self.max_response_bytes:
                        raise ValueError(f"response exceeds limit: {len(raw)} bytes")
                    headers = {key: value for key, value in response.headers.items()}
                    return HttpResponse(raw, getattr(response, "status", None), response.geturl(), headers, attempt)
            except Exception as exc:
                last_error = exc
                if attempt <= self.retries:
                    time.sleep(min(0.25 * attempt, 1.0))
        if isinstance(last_error, HTTPError):
            raise last_error
        raise last_error or RuntimeError("page fetch failed")
