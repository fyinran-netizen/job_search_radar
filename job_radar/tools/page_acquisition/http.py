"""HTTP page acquisition tool for manually configured URLs."""

from pathlib import Path
import re
import time
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, url2pathname, urlopen
from urllib.error import HTTPError

from pydantic import BaseModel

from job_radar.infra.logging import get_logger
from job_radar.tools.web_search.models import CandidateSource
from job_radar.tools.page_acquisition.models import PageDocument, PageFetchEvidence
from job_radar.tools.page_acquisition.browser import BrowserPageTool
from job_radar.tools.page_acquisition.recovery import recover_page
from job_radar.tools.page_acquisition.technical_triage import detect_recovery_sources
from job_radar.tools.base import BaseTool

logger = get_logger(__name__)


class HttpPageTool(BaseTool):
    """Fetch bytes/text and return collection facts, without parsing HTML."""

    name = "acquire_page"

    def __init__(self, timeout_seconds: int = 20, retries: int = 2, browser_fallback: Any = None) -> None:
        self.timeout_seconds = timeout_seconds
        self.retries = max(0, retries)
        self.browser_fallback = browser_fallback if browser_fallback is not None else BrowserPageTool(timeout_seconds=timeout_seconds)

    def run(self, payload: BaseModel | dict[str, Any]) -> PageDocument:
        """Fetch content and preserve only raw content and fetch evidence."""

        source = payload if isinstance(payload, CandidateSource) else CandidateSource.model_validate(payload)
        started = time.perf_counter()
        logger.info("acquisition_start url=%s http_retries=%s browser_fallback=%s", source.url, self.retries, type(self.browser_fallback).__name__)
        try:
            html, evidence = self._read_url(source.url)
            logger.info("acquisition_http_complete url=%s status=%s attempts=%s html_chars=%s", source.url, evidence.status_code, evidence.attempts, len(html))
            if self._needs_browser_fallback(html, evidence):
                candidate = self._page(source, html, evidence)
                recovered, result = recover_page(
                    candidate,
                    available_sources=detect_recovery_sources(candidate),
                )
                if result.success:
                    logger.info("acquisition_recovery_complete url=%s method=%s recovered_chars=%s", source.url, result.source, len(result.text))
                    return recovered
                raise RuntimeError("HTTP response was empty or an obvious JavaScript shell")
        except Exception as exc:
            try:
                page = self.browser_fallback.run(source) if hasattr(self.browser_fallback, "run") else self.browser_fallback(source)
                logger.info("acquisition_browser_complete url=%s method=%s attempts=%s html_chars=%s", source.url, page.fetch_evidence.fetch_method, page.fetch_evidence.attempts, len(page.html))
                return page.model_copy(update={"fetch_evidence": page.fetch_evidence.model_copy(update={"fetch_method": "browser", "attempts": page.fetch_evidence.attempts + self.retries + 1})})
            except Exception as browser_exc:
                evidence = PageFetchEvidence(
                    status_code=exc.code if isinstance(exc, HTTPError) else None,
                    final_url=exc.geturl() if isinstance(exc, HTTPError) else None,
                    fetch_method="http_then_browser",
                    error=f"http: {exc}; browser: {browser_exc}",
                    attempts=self.retries + 1,
                )
                html = ""
        fetch_metadata = evidence.model_dump(exclude_none=True)
        logger.info("acquisition_complete url=%s method=%s status=%s elapsed_ms=%.1f error=%s", source.url, evidence.fetch_method, evidence.status_code, (time.perf_counter() - started) * 1000, bool(evidence.error))
        return self._page(source, html, evidence)

    @staticmethod
    def _page(source: CandidateSource, html: str, evidence: PageFetchEvidence) -> PageDocument:
        """Build the raw acquired document with source provenance."""
        fetch_metadata = evidence.model_dump(exclude_none=True)
        return PageDocument(
            url=source.url,
            source_name=source.source_name,
            title="",
            text="",
            html=html,
            metadata={
                **fetch_metadata,
                "company_name": source.company_name,
                "company_type": source.company_type,
                "location": source.location,
                "source_title": source.title,
                "source_reason": source.reason,
                "is_official": source.is_official,
            },
            fetch_evidence=evidence,
        )

    @staticmethod
    def _needs_browser_fallback(html: str, evidence: PageFetchEvidence) -> bool:
        """Detect technical collection failures without judging page meaning."""
        if (evidence.status_code is not None and not 200 <= evidence.status_code < 300) or not html.strip():
            return True
        lowered = html.lower()
        return bool(
            re.search(r"<div[^>]+(?:id|class)=[\"'][^\"']*(?:app|root|__next)[^\"']*[\"'][^>]*>\s*</div>", lowered)
            or (re.search(r"<script[^>]+src=[\"'][^\"']+\.js(?:[\"']|\?)", lowered) and len(re.sub(r"<[^>]+>", "", html).strip()) < 200)
        )

    def _read_url(self, url: str) -> tuple[str, PageFetchEvidence]:
        parsed = urlparse(url)
        if parsed.scheme == "file":
            return Path(url2pathname(parsed.path)).read_text(encoding="utf-8"), PageFetchEvidence(status_code=200, final_url=url, content_type="text/html; charset=utf-8", fetch_method="file", attempts=1)
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 2):
            try:
                request = Request(url, headers={"User-Agent": "JobRadar/0.1 local research tool", "Accept": "text/html,application/xhtml+xml"})
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    raw = response.read()
                    content_type = response.headers.get("Content-Type", "")
                    evidence = PageFetchEvidence(status_code=getattr(response, "status", None), final_url=response.geturl(), content_type=content_type, fetch_method="http", attempts=attempt)
                return raw.decode(self._detect_encoding(content_type, raw), errors="replace"), evidence
            except Exception as exc:
                last_error = exc
                if attempt <= self.retries:
                    time.sleep(min(0.25 * attempt, 1.0))
        raise last_error or RuntimeError("page fetch failed")

    @staticmethod
    def _detect_encoding(content_type: str, raw: bytes) -> str:
        header_match = re.search(r"charset=([\w-]+)", content_type, re.I)
        if header_match:
            return header_match.group(1)
        head = raw[:4096].decode("ascii", errors="ignore")
        meta_match = re.search(r"charset=['\"]?([\w-]+)", head, re.I)
        if meta_match:
            return meta_match.group(1)
        return "utf-8"


