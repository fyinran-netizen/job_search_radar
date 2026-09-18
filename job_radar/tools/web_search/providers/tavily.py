"""Tavily-backed web search exposed through the single ``web_search`` tool."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from pydantic import BaseModel, TypeAdapter

from job_radar.tools.base import BaseTool
from job_radar.tools.web_search.models import CandidateSource, SearchPlan
from job_radar.tools.web_search.url_utils import normalize_url


class TavilyWebSearchTool(BaseTool):
    """Execute bounded searches for a SearchPlan and return CandidateSource[]."""

    name = "web_search"

    def __init__(self, max_sources: int = 10, timeout_seconds: int = 30) -> None:
        self.max_sources = max_sources
        self.timeout_seconds = timeout_seconds

    def run(self, payload: BaseModel | dict[str, Any]) -> list[CandidateSource]:
        plan = payload if isinstance(payload, SearchPlan) else SearchPlan.model_validate(payload)
        api_key = os.getenv("TAVILY_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("TAVILY_API_KEY is not configured")

        sources: list[CandidateSource] = []
        seen_urls: set[str] = set()
        quotas = self._query_quotas(len(plan.queries))
        for query, quota in zip(plan.queries, quotas):
            if quota <= 0:
                continue
            results = self._search(api_key, query, quota)
            for item in results:
                source = self._to_candidate_source(item, query)
                if source is None:
                    continue
                normalized_url = normalize_url(source.url)
                if normalized_url in seen_urls:
                    continue
                seen_urls.add(normalized_url)
                sources.append(source)
                if len(sources) >= self.max_sources:
                    break
        return sources

    def _query_quotas(self, query_count: int) -> list[int]:
        """Split the source budget as evenly as possible across queries."""
        if query_count <= 0 or self.max_sources <= 0:
            return [0] * query_count
        base, remainder = divmod(self.max_sources, query_count)
        return [base + int(index < remainder) for index in range(query_count)]

    def _search(self, api_key: str, query: str, max_results: int) -> list[dict[str, Any]]:
        body = json.dumps({
            "api_key": api_key,
            "query": query,
            "search_depth": "basic",
            "max_results": max_results,
            "include_answer": False,
        }).encode("utf-8")
        request = Request(
            "https://api.tavily.com/search",
            data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            data = json.loads(response.read().decode("utf-8"))
        return TypeAdapter(list[dict[str, Any]]).validate_python(data.get("results", []))

    @staticmethod
    def _to_candidate_source(item: dict[str, Any], query: str) -> CandidateSource | None:
        url = item.get("url")
        if not isinstance(url, str) or not url.strip():
            return None
        title = item.get("title")
        parsed = urlparse(url)
        return CandidateSource(
            url=url,
            title=title if isinstance(title, str) and title else url,
            source_name=parsed.netloc or url,
            relevance_score=round(float(item.get("score", 0)) * 100),
            reason=f"Tavily result for: {query}; {item.get('content', '')}"[:1000],
        )
