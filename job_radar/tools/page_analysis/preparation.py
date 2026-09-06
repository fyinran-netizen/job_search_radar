"""Single-pass deterministic preparation of acquired pages."""

import re
from dataclasses import dataclass
from urllib.parse import urlparse, urljoin

from job_radar.tools.page_acquisition.models import PageDocument
from job_radar.tools.page_analysis.cleaning import CleanedText, clean_page_text, parse_acquired_page
from job_radar.tools.page_analysis.models import AIPageInput, ImportantLink, PageAnalysisTrace

_VISIBLE_URL_PATTERN = re.compile(r"https?://[^\s<>\"']+")
_TRAILING_URL_PUNCTUATION = ".,;:!?)]}，。；：！？）】』"  # common URL punctuation
_EXCERPT_MARKERS = (
    "职位介绍", "岗位职责", "工作职责", "岗位要求", "任职要求",
    "responsibilities", "requirements", "qualifications", "job description",
)


@dataclass(frozen=True)
class PreparedPage:
    """Prepared page plus the audit record used by classification."""

    page: AIPageInput
    trace: PageAnalysisTrace


def build_classification_excerpt(title: str, visible_text: str, max_chars: int = 6000) -> str:
    """Build a deterministic, section-aware excerpt within the hard limit."""
    if max_chars <= 0:
        return ""
    lines = [line.strip() for line in visible_text.splitlines() if line.strip()]
    blocks: list[str] = []
    for index, line in enumerate(lines):
        lowered = line.casefold()
        if any(marker.casefold() in lowered for marker in _EXCERPT_MARKERS):
            blocks.append("\n".join(lines[index:index + 12]))
    if blocks:
        candidate = "\n".join([title.strip(), *blocks]) if title.strip() else "\n".join(blocks)
    else:
        body = "\n".join(lines)
        head = body[: max_chars // 2]
        tail = body[-(max_chars - len(head)) :] if len(body) > len(head) else ""
        candidate = "\n".join(part for part in (title.strip(), head, tail) if part)
    return candidate[:max_chars].rstrip()


def prepare_page(page: PageDocument, max_text_chars: int = 12000, classification_max_chars: int = 6000) -> PreparedPage:
    """Parse, clean, link-extract, and build one AI input exactly once."""
    parsed = parse_acquired_page(page)
    cleaned = clean_page_text(parsed.html, parsed.text, url=parsed.url, max_text_chars=max_text_chars)
    ai_page = build_ai_page_input(parsed, cleaned)
    excerpt = build_classification_excerpt(ai_page.title, ai_page.visible_text, classification_max_chars)
    trace = PageAnalysisTrace(
        url=ai_page.url,
        cleaning_method=cleaned.method,
        original_chars=cleaned.original_chars,
        cleaned_chars=cleaned.cleaned_chars,
        removed_line_count=cleaned.removed_line_count,
        truncated=cleaned.truncated,
        classification_text=excerpt,
        classification_text_length=len(excerpt),
        classification_truncated=len(excerpt) >= classification_max_chars and len(ai_page.title) + len(ai_page.visible_text) > classification_max_chars,
    )
    return PreparedPage(ai_page, trace)


def build_ai_page_input(page: PageDocument, cleaned: CleanedText | None = None, max_text_chars: int = 12000) -> AIPageInput:
    """Build an input from an already parsed page; parsing never happens here."""
    cleaned = cleaned or clean_page_text(page.html, page.text, url=page.url, max_text_chars=max_text_chars)
    final_url = page.metadata.get("final_url")
    return AIPageInput(
        url=page.url,
        final_url=final_url if isinstance(final_url, str) else None,
        source_name=page.source_name,
        source_company_name=_optional_metadata_string(page, "company_name"),
        company_type=_optional_metadata_string(page, "company_type"),
        source_location=_optional_metadata_string(page, "location"),
        is_official=bool(page.metadata.get("is_official", False)),
        title=page.title,
        visible_text=cleaned.text,
        important_links=extract_important_links(page),
    )


def extract_important_links(page: PageDocument, max_links: int = 10) -> list[ImportantLink]:
    links = page.metadata.get("links", [])
    if not isinstance(links, list):
        links = []
    found: list[ImportantLink] = []
    seen: set[str] = set()
    for link in links:
        if not isinstance(link, dict) or not isinstance(link.get("href"), str) or not link["href"]:
            continue
        url = urljoin(page.url, link["href"])
        if url in seen:
            continue
        item = _classify_link(url, str(link.get("text") or "").strip())
        if item:
            found.append(item)
            seen.add(url)
    for item in _extract_visible_text_links(page.text):
        if item.url not in seen:
            found.append(item)
            seen.add(item.url)
    priority = {"apply": 0, "attachment": 1, "source": 2, "other": 3}
    return sorted(found, key=lambda item: priority[item.kind])[:max_links]


def _classify_link(url: str, text: str) -> ImportantLink | None:
    path = urlparse(url).path.casefold()
    if path.endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx")):
        return ImportantLink(url=url, text=text, kind="attachment", reason="document_file")
    lowered = text.casefold()
    if any(marker in lowered for marker in ("apply", "application", "submit", "resume", "申请", "报名", "应聘")):
        return ImportantLink(url=url, text=text, kind="apply", reason="apply_signal")
    if any(marker in lowered for marker in ("source", "original source", "来源")):
        return ImportantLink(url=url, text=text, kind="source", reason="source_signal")
    return None


def _extract_visible_text_links(text: str) -> list[ImportantLink]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    results: list[ImportantLink] = []
    for index, line in enumerate(lines):
        context = " ".join(lines[max(0, index - 1): index + 2]).casefold()
        if not any(marker in context for marker in ("apply", "application", "申请", "报名", "应聘")):
            continue
        for match in _VISIBLE_URL_PATTERN.finditer(line):
            url = match.group(0).rstrip(_TRAILING_URL_PUNCTUATION)
            if not urlparse(url).path.casefold().endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx")):
                results.append(ImportantLink(url=url, text=line, kind="apply", reason="visible_text_apply_url"))
    return results


def _optional_metadata_string(page: PageDocument, key: str) -> str | None:
    value = page.metadata.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None
