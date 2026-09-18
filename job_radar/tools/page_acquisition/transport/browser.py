"""Playwright/browser transport. It only renders and returns HTML."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class BrowserResponse:
    html: str
    final_url: str | None
    attempts: int = 1
    status_code: int | None = 200


class BrowserTransport:
    def __init__(self, collector: Callable[[str], str] | None = None, timeout_seconds: int = 30) -> None:
        self.collector = collector
        self.timeout_seconds = timeout_seconds

    def fetch(self, url: str) -> BrowserResponse:
        if self.collector:
            html = self.collector(url)
            if not html:
                raise RuntimeError("browser collection returned empty content")
            return BrowserResponse(html, url, status_code=200)
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("Playwright is not installed") from exc
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                response = page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_seconds * 1000)
                html = page.content()
                if not html:
                    raise RuntimeError("browser collection returned empty content")
                return BrowserResponse(html, page.url or (response.url if response else url), status_code=response.status if response else 200)
            finally:
                browser.close()
