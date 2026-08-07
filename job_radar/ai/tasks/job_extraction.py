"""AI-backed job extraction task with minimal page input."""

from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, TypeAdapter

from job_radar.ai.prompt_builder import build_json_prompt
from job_radar.ai.providers.base import AIProvider
from job_radar.ai.skill_loader import load_skill
from job_radar.models.job import RawJobRecord
from job_radar.models.tool import PageContent
from job_radar.pipeline.page_cleaning import clean_page_text


class ImportantLink(BaseModel):
    """A relevant page link preserved for AI extraction context."""

    url: str
    text: str = ""
    kind: Literal["attachment", "apply", "source", "other"] = "other"
    reason: str = ""


class AIPageInput(BaseModel):
    """Minimal page payload sent to AI extraction."""

    url: str
    final_url: str | None = None
    title: str
    visible_text: str = Field(description="Cleaned visible page text, truncated before prompting.")
    important_links: list[ImportantLink] = Field(default_factory=list)


def build_ai_page_input(page: PageContent, max_text_chars: int = 12000) -> AIPageInput:
    """Trim collected page content to the fields AI extraction actually needs."""

    final_url = page.metadata.get("final_url")
    return AIPageInput(
        url=page.url,
        final_url=final_url if isinstance(final_url, str) else None,
        title=page.title,
        visible_text=clean_page_text(
            page.html,
            page.text,
            url=page.url,
            max_text_chars=max_text_chars,
        ).text,
        important_links=extract_important_links(page),
    )


def extract_important_links(page: PageContent, max_links: int = 10) -> list[ImportantLink]:
    """Preserve useful apply, attachment, and source links from collected metadata."""

    links = page.metadata.get("links", [])
    if not isinstance(links, list):
        return []

    important_links: list[ImportantLink] = []
    seen_urls: set[str] = set()
    for link in links:
        if not isinstance(link, dict):
            continue
        url = link.get("href")
        if not isinstance(url, str) or not url:
            continue
        if url in seen_urls:
            continue
        text = link.get("text")
        link_text = text.strip() if isinstance(text, str) else ""
        important_link = _classify_link(url, link_text)
        if important_link is None:
            continue
        important_links.append(important_link)
        seen_urls.add(url)
        if len(important_links) >= max_links:
            break
    return important_links


def _classify_link(url: str, text: str) -> ImportantLink | None:
    combined = f"{url} {text}".lower()
    text_lower = text.lower()
    path = urlparse(url).path.lower()
    if path.endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx")):
        return ImportantLink(url=url, text=text, kind="attachment", reason="document_file")
    if _contains_any(
        combined,
        [
            "apply",
            "application",
            "submit",
            "resume",
            "\u6295\u9012",
            "\u7533\u8bf7",
            "\u62a5\u540d",
            "\u7b80\u5386",
            "\u7f51\u7533",
            "\u5e94\u8058",
        ],
    ):
        return ImportantLink(url=url, text=text, kind="apply", reason="apply_signal")
    if _contains_any(
        text_lower,
        [
            "source",
            "original source",
            "\u6765\u6e90",
        ],
    ):
        return ImportantLink(url=url, text=text, kind="source", reason="source_signal")
    return None


def _contains_any(text: str, markers: list[str]) -> bool:
    return any(marker in text for marker in markers)


class AIJobExtractionClient:
    """Extract RawJobRecord objects from PageContent through a structured AI provider."""

    def __init__(
        self,
        provider: AIProvider,
        skill_name: str = "job-extraction",
        max_text_chars: int = 12000,
        timeout_seconds: int = 240,
    ) -> None:
        self.provider = provider
        self.skill_name = skill_name
        self.max_text_chars = max_text_chars
        self.timeout_seconds = timeout_seconds

    def extract_jobs_from_page(self, page: PageContent) -> list[RawJobRecord]:
        """Build a minimal prompt payload and validate RawJobRecord[] output."""

        payload = build_ai_page_input(page, max_text_chars=self.max_text_chars)
        skill = load_skill(self.skill_name)
        prompt = build_json_prompt(
            skill,
            {
                "page": payload.model_dump(),
                "output": "Return a JSON array of RawJobRecord objects.",
            },
        )
        data = self.provider.generate_json(prompt, timeout_seconds=self.timeout_seconds)
        return TypeAdapter(list[RawJobRecord]).validate_python(data)
