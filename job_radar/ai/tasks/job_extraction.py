"""AI-backed job extraction task with minimal page input."""

import re
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
    """Cleaned page text plus deterministic provenance kept outside AI output."""

    url: str
    final_url: str | None = None
    source_name: str | None = None
    source_company_name: str | None = None
    company_type: str | None = None
    is_official: bool = False
    title: str
    visible_text: str = Field(description="Cleaned visible page text, truncated before prompting.")
    important_links: list[ImportantLink] = Field(default_factory=list)


class ExtractedPageContext(BaseModel):
    """Semantic fields shared by every job extracted from one source page."""

    company_name: str | None = None
    recruitment_type: str | None = None
    graduation_years: list[str | int] = Field(default_factory=list)
    published_at: str | None = None
    deadline: str | None = None


class ExtractedJobDetail(BaseModel):
    """Fields that vary between jobs listed on the same page."""

    title: str | None = None
    location: str | None = None
    description: str | None = None
    requirements: str | None = None


class PageJobExtraction(BaseModel):
    """Compact AI response for one page before RawJobRecord expansion."""

    page_id: str
    page_context: ExtractedPageContext
    jobs: list[ExtractedJobDetail] = Field(default_factory=list)

    def to_raw_records(self, page_input: AIPageInput) -> list[RawJobRecord]:
        """Merge AI semantics with deterministic page provenance."""

        context = self.page_context.model_dump()
        context["company_name"] = context.get("company_name") or page_input.source_company_name
        context.update(
            {
                "company_type": page_input.company_type,
                "apply_url": _first_apply_url(page_input.important_links),
                "source_url": page_input.url,
                "source_name": page_input.source_name or _source_name_from_url(page_input),
                "is_official": page_input.is_official,
            }
        )
        return [
            RawJobRecord.model_validate({**context, **job.model_dump()})
            for job in self.jobs
        ]


def build_ai_page_input(page: PageContent, max_text_chars: int = 12000) -> AIPageInput:
    """Trim collected page content to the fields AI extraction actually needs."""

    final_url = page.metadata.get("final_url")
    return AIPageInput(
        url=page.url,
        final_url=final_url if isinstance(final_url, str) else None,
        source_name=page.source_name,
        source_company_name=_optional_metadata_string(page, "company_name"),
        company_type=_optional_metadata_string(page, "company_type"),
        is_official=bool(page.metadata.get("is_official", False)),
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
    for link in _extract_visible_text_links(page.text):
        if link.url in seen_urls:
            continue
        important_links.append(link)
        seen_urls.add(link.url)

    priority = {"apply": 0, "attachment": 1, "source": 2, "other": 3}
    return sorted(important_links, key=lambda link: priority[link.kind])[:max_links]


def _classify_link(url: str, text: str) -> ImportantLink | None:
    text_lower = text.lower()
    path = urlparse(url).path.lower()
    if path.endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx")):
        return ImportantLink(url=url, text=text, kind="attachment", reason="document_file")
    if _contains_any(
        text_lower,
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


_VISIBLE_URL_PATTERN = re.compile(r"https?://[^\s<>\"']+")
_TRAILING_URL_PUNCTUATION = ".,;:!?)]}，。；：！？）】}"


def _extract_visible_text_links(text: str) -> list[ImportantLink]:
    """Find explicit apply URLs in visible text using nearby recruitment labels."""

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    links: list[ImportantLink] = []
    for index, line in enumerate(lines):
        context_start = max(0, index - 1)
        context_end = min(len(lines), index + 2)
        context = " ".join(lines[context_start:context_end]).lower()
        if not _contains_any(
            context,
            ["apply", "application", "报名", "投递", "网申", "招聘网站", "校招官网"],
        ):
            continue
        for match in _VISIBLE_URL_PATTERN.finditer(line):
            url = match.group(0).rstrip(_TRAILING_URL_PUNCTUATION)
            if urlparse(url).path.lower().endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx")):
                continue
            links.append(ImportantLink(url=url, text=line, kind="apply", reason="visible_text_apply_url"))
    return links


def _contains_any(text: str, markers: list[str]) -> bool:
    return any(marker in text for marker in markers)


def _first_apply_url(links: list[ImportantLink]) -> str | None:
    for link in links:
        if link.kind == "apply":
            return link.url
    return None


def _source_name_from_url(page_input: AIPageInput) -> str:
    parsed = urlparse(page_input.final_url or page_input.url)
    return parsed.netloc or page_input.title or page_input.url


def _optional_metadata_string(page: PageContent, key: str) -> str | None:
    value = page.metadata.get(key)
    return value if isinstance(value, str) and value.strip() else None


def _semantic_page_payload(page_input: AIPageInput, page_id: str) -> dict[str, str]:
    """Return only text fields that require AI interpretation."""

    return {
        "page_id": page_id,
        "title": page_input.title,
        "visible_text": page_input.visible_text,
    }


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
        return self.extract_jobs_from_input(payload)

    def extract_jobs_from_input(
        self,
        payload: AIPageInput,
        retry_instruction: str | None = None,
    ) -> list[RawJobRecord]:
        """Extract a compact page response and expand it to RawJobRecord[]."""

        skill = load_skill(self.skill_name)
        prompt = build_json_prompt(
            skill,
            {
                "page": _semantic_page_payload(payload, "page-1"),
                "output": (
                    "Return one JSON object with the same page_id, semantic page_context fields, "
                    "and per-job title, location, description, and requirements. Return every "
                    "explicitly named position even when one or more job fields are null."
                    + (f" {retry_instruction}" if retry_instruction else "")
                ),
            },
        )
        data = self.provider.generate_json(prompt, timeout_seconds=self.timeout_seconds)
        extraction = PageJobExtraction.model_validate(data)
        if extraction.page_id != "page-1":
            raise ValueError(f"Unexpected extraction page_id: {extraction.page_id}")
        return extraction.to_raw_records(payload)

    def extract_jobs_from_inputs(
        self,
        payloads: list[AIPageInput],
        retry_instruction: str | None = None,
    ) -> list[RawJobRecord]:
        """Extract compact page responses and expand them to RawJobRecord[]."""

        if not payloads:
            return []
        if len(payloads) == 1:
            return self.extract_jobs_from_input(payloads[0], retry_instruction=retry_instruction)

        skill = load_skill(self.skill_name)
        pages_by_id = {f"page-{index}": payload for index, payload in enumerate(payloads, start=1)}
        prompt = build_json_prompt(
            skill,
            {
                "pages": [
                    _semantic_page_payload(payload, page_id)
                    for page_id, payload in pages_by_id.items()
                ],
                "output": (
                    "Return a JSON array with one object per input page. Each object must contain "
                    "the unchanged page_id, semantic page_context fields, and every explicitly "
                    "named position, even when one or more job fields are null."
                    + (f" {retry_instruction}" if retry_instruction else "")
                ),
            },
        )
        data = self.provider.generate_json(prompt, timeout_seconds=self.timeout_seconds)
        if isinstance(data, dict) and len(payloads) == 1:
            extractions = [PageJobExtraction.model_validate(data)]
        else:
            extractions = TypeAdapter(list[PageJobExtraction]).validate_python(data)
        extracted_ids = [extraction.page_id for extraction in extractions]
        if len(extracted_ids) != len(set(extracted_ids)):
            raise ValueError("AI extraction returned duplicate page_id values.")
        if set(extracted_ids) != set(pages_by_id):
            raise ValueError("AI extraction page_id values do not match the input pages.")
        return [
            record
            for extraction in extractions
            for record in extraction.to_raw_records(pages_by_id[extraction.page_id])
        ]
