"""Orchestrates transport, decoding, technical inspection, structure, and recovery."""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel

from job_radar.infra.logging import get_logger
from job_radar.tools.base import BaseTool
from job_radar.tools.page_acquisition.models import PageDocument, PageFetchEvidence
from job_radar.tools.page_acquisition.processing.decoding import decode_response
from job_radar.tools.page_acquisition.processing.inspection import inspect_content
from job_radar.tools.page_acquisition.processing.structure import structure_page
from job_radar.tools.page_acquisition.transport.browser import BrowserTransport
from job_radar.tools.page_acquisition.transport.http import HttpTransport
from job_radar.tools.web_search.models import CandidateSource

logger = get_logger(__name__)


class PageAcquisitionPipeline(BaseTool):
    name = "acquire_page"

    def __init__(self, timeout_seconds: int = 20, retries: int = 2, browser_fallback: Any = None, max_response_bytes: int = 2_000_000) -> None:
        self.http = HttpTransport(timeout_seconds, retries, max_response_bytes)
        self.browser = browser_fallback or BrowserTransport(timeout_seconds=timeout_seconds)
        self.retries = max(0, retries); self.max_response_bytes = max_response_bytes

    def run(self, payload: BaseModel | dict[str, Any]) -> PageDocument:
        source = payload if isinstance(payload, CandidateSource) else CandidateSource.model_validate(payload)
        try:
            response = self.http.fetch(source.url)
            headers = dict(response.headers)
            content_type = _header(headers, "content-type")
            resource_kind = _resource_kind(content_type)
            evidence = PageFetchEvidence(status_code=response.status_code, final_url=response.final_url, content_type=content_type, fetch_method=response.fetch_method, attempts=response.attempts)

            if resource_kind in {"image", "pdf", "binary"}:
                return self._page(
                    source,
                    "",
                    evidence,
                    {
                        "resource_kind": resource_kind,
                        "acquisition_status": "unsupported_non_text",
                        "technical_checks": ["unsupported_non_text"],
                    },
                )

            decoded = decode_response(response.raw_bytes, headers)
            page = self._page(source, decoded.text, evidence, {"charset": decoded.charset, "content_encoding": decoded.content_encoding, "resource_kind": resource_kind})
            if resource_kind == "json":
                return page.model_copy(update={"metadata": {**page.metadata, "acquisition_status": "identified_unparsed", "technical_checks": ["json_unparsed"]}})
            reasons = inspect_content(decoded.text, status_code=response.status_code, content_type=evidence.content_type, max_response_bytes=self.max_response_bytes)
            if reasons and any(reason in {"empty_page", "javascript_shell", "access_interstitial", "binary_or_mojibake", "response_too_large"} for reason in reasons):
                return self._browser_or_page(source, page, reasons)
            return structure_page(page)
        except Exception as exc:
            reason = "response_too_large" if "exceeds limit" in str(exc).lower() else "http_failed"
            return self._browser_or_page(source, self._page(source, "", PageFetchEvidence(fetch_method="http_then_browser", error=str(exc), attempts=self.retries + 1)), [reason])

    def _browser_or_page(self, source, http_page, reasons):
        try:
            if hasattr(self.browser, "fetch"):
                response = self.browser.fetch(source.url)
            elif hasattr(self.browser, "run"):
                response = self.browser.run(source)
            else:
                response = self.browser(source.url)
            if isinstance(response, PageDocument): page = response
            elif isinstance(response, str): page = self._page(source, response, PageFetchEvidence(final_url=source.url, content_type="text/html", fetch_method="browser", attempts=1))
            else: page = self._page(source, response.html, PageFetchEvidence(status_code=response.status_code, final_url=response.final_url, content_type="text/html", fetch_method="browser", attempts=response.attempts))
            return structure_page(page.model_copy(update={"metadata": {**http_page.metadata, **page.metadata, "technical_checks": reasons}, "fetch_evidence": page.fetch_evidence.model_copy(update={"fetch_method": "browser"})}))
        except Exception as browser_exc:
            evidence = http_page.fetch_evidence.model_copy(update={
                "fetch_method": "http_then_browser",
                "error": f"{http_page.fetch_evidence.error or 'technical check failed'}; browser: {browser_exc}",
            })
            return http_page.model_copy(update={"metadata": {**http_page.metadata, "technical_checks": reasons}, "fetch_evidence": evidence})

    @staticmethod
    def _page(source, html, evidence, extra=None):
        metadata = {**(extra or {}), **evidence.model_dump(exclude_none=True), "company_name": source.company_name, "company_type": source.company_type, "location": source.location, "source_title": source.title, "source_reason": source.reason, "is_official": source.is_official}
        return PageDocument(url=source.url, source_name=source.source_name, html=html, metadata=metadata, fetch_evidence=evidence)


class BrowserPageTool(BaseTool):
    """Public browser-only acquisition entry point using the browser transport."""

    name = "acquire_page_browser"

    def __init__(self, collector=None, timeout_seconds: int = 30) -> None:
        self.transport = BrowserTransport(collector=collector, timeout_seconds=timeout_seconds)

    def run(self, payload: BaseModel | dict[str, Any]) -> PageDocument:
        source = payload if isinstance(payload, CandidateSource) else CandidateSource.model_validate(payload)
        response = self.transport.fetch(source.url)
        page = PageAcquisitionPipeline._page(
            source,
            response.html,
            PageFetchEvidence(status_code=response.status_code, final_url=response.final_url, content_type="text/html", fetch_method="browser", attempts=response.attempts),
        )
        return structure_page(page)


def _header(headers, name):
    return next((value for key, value in headers.items() if key.lower() == name), "")


def _resource_kind(content_type: str) -> str:
    lowered = content_type.lower()
    if "pdf" in lowered: return "pdf"
    if lowered.startswith("image/"): return "image"
    if "json" in lowered: return "json"
    if "html" in lowered or "xhtml" in lowered: return "html"
    return "binary" if content_type and not lowered.startswith("text/") else "unknown"
