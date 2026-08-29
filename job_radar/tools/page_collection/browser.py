"""Rendered browser collection used after ordinary HTTP is insufficient."""

from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel

from job_radar.tools.base import BaseTool
from job_radar.tools.page_collection.models import PageContent, PageFetchEvidence
from job_radar.tools.web_search.models import CandidateSource


class BrowserPageTool(BaseTool):
    """Collect raw page content with an injected browser or Playwright."""

    name = "collect_page_browser"

    def __init__(self, collector: Callable[[str], str] | None = None, timeout_seconds: int = 30) -> None:
        self.collector = collector
        self.timeout_seconds = timeout_seconds

    def run(self, payload: BaseModel | dict[str, Any]) -> PageContent:
        source = payload if isinstance(payload, CandidateSource) else CandidateSource.model_validate(payload)
        try:
            html = self.collector(source.url) if self.collector else self._playwright_fetch(source.url)
        except Exception as exc:
            raise RuntimeError(f"browser collection failed: {exc}") from exc
        if not html:
            raise RuntimeError("browser collection returned empty content")
        return PageContent(
            url=source.url,
            source_name=source.source_name,
            html=html,
            metadata={
                "company_name": source.company_name,
                "company_type": source.company_type,
                "location": source.location,
                "source_title": source.title,
                "source_reason": source.reason,
                "is_official": source.is_official,
            },
            fetch_evidence=PageFetchEvidence(
                final_url=source.url,
                content_type="text/html",
                fetch_method="browser",
                attempts=1,
            ),
        )

    def _playwright_fetch(self, url: str) -> str:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("Playwright is not installed") from exc
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_seconds * 1000)
                return page.content()
            finally:
                browser.close()
