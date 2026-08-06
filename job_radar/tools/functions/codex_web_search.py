"""Codex CLI-backed web search tool."""

import json
from typing import Any

from pydantic import BaseModel, TypeAdapter

from job_radar.ai.providers.codex_cli import CodexCliProvider
from job_radar.models.search import CandidateSource, SearchPlan
from job_radar.tools.base import BaseTool


class CodexWebSearchTool(BaseTool):
    """Use local Codex CLI web search to return candidate job URLs."""

    name = "web_search"

    def __init__(
        self,
        provider: CodexCliProvider | None = None,
        max_sources: int = 10,
    ) -> None:
        self.provider = provider or CodexCliProvider()
        self.max_sources = max_sources

    def run(self, payload: BaseModel | dict[str, Any]) -> list[CandidateSource]:
        """Search for candidate job URLs from a static search plan."""

        plan = payload if isinstance(payload, SearchPlan) else SearchPlan.model_validate(payload)
        prompt = self._build_prompt(plan)
        data = self.provider.generate_json(prompt, timeout_seconds=240)
        sources = TypeAdapter(list[CandidateSource]).validate_python(data)
        return sources[: self.max_sources]

    def _build_prompt(self, plan: SearchPlan) -> str:
        schema = json.dumps(CandidateSource.model_json_schema(), ensure_ascii=False, indent=2)
        plan_text = json.dumps(plan.model_dump(), ensure_ascii=False, indent=2)
        return f"""
You are Job Radar's web_search tool implementation.

Use web search to find candidate job posting URLs for the provided SearchPlan.
Return concrete URLs worth fetching later. Do not fetch or summarize full pages.

SearchPlan:
{plan_text}

Return ONLY a JSON array. Each item must match this CandidateSource schema:
{schema}

Rules:
- Prefer official company career pages and concrete job detail pages.
- Include third-party job pages only when they look like real job descriptions.
- Avoid generic landing pages, login-only pages, forums, SEO pages, application submission pages, and duplicate URLs.
- Prefer pages matching target role, graduation cohort, location, and company type.
- Set relevance_score from 0 to 100.
- Set is_official true only when the source appears to be an official company or recruitment site.
- Include a concise reason for each URL.
- Return at most {self.max_sources} sources.
""".strip()
