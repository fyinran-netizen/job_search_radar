"""正文提取与保守清理。

HTML 的 title、visible text 和 links 由 page_acquisition.structure 提供；本模块
只对正文候选做提取、规范化、去噪和截断，不重新解析页面结构。
"""

import re

from pydantic import BaseModel
from trafilatura import extract


_URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)


HIGH_CONFIDENCE_CHROME_LINES = {
    # English
    "cookie settings",
    "accept cookies",
    "privacy policy",
    "terms of use",

    # Chinese
    "隐私政策",
    "隐私声明",
    "用户协议",
    "使用条款",
    "服务条款",
    "接受全部cookie",
    "接受所有cookie",
    "cookie设置",
}


class CleanedText(BaseModel):
    """Cleaned visible text with lightweight audit information."""

    text: str
    method: str
    original_chars: int
    cleaned_chars: int
    original_line_count: int
    kept_line_count: int
    removed_line_count: int
    truncated: bool


def clean_page_text(html: str, fallback_text: str, url: str = "", max_text_chars: int = 12000, min_extracted_chars: int = 300) -> CleanedText:
    """Extract the main body from acquired HTML, then clean it.

    ``fallback_text`` is already acquisition-produced visible text. It is never
    reparsed here; trafilatura is only used as the Analysis body extractor.
    """
    extracted_text = _extract_with_trafilatura(html, url)
    if extracted_text and len(extracted_text.strip()) >= min_extracted_chars:
        return clean_visible_text(extracted_text, max_text_chars=max_text_chars, method="trafilatura", original_chars=len(fallback_text))
    return clean_visible_text(fallback_text, max_text_chars=max_text_chars, method="fallback_text", original_chars=len(fallback_text))


def clean_visible_text(text: str, max_text_chars: int = 12000, method: str = "fallback_text", original_chars: int | None = None) -> CleanedText:
    """Normalize body text and remove likely structural chrome conservatively."""
    original_lines = text.splitlines()
    normalized_lines = [_normalize_line(line) for line in original_lines]
    line_counts = {line: normalized_lines.count(line) for line in set(normalized_lines) if line}
    kept_lines: list[str] = []
    seen_short_lines: dict[str, int] = {}
    removed_line_count = 0

    for index, line in enumerate(normalized_lines):
        if not line:
            removed_line_count += 1
            continue
        if _is_boilerplate_line(line, index, normalized_lines, line_counts):
            removed_line_count += 1
            continue
        if _is_repeated_short_line(line, seen_short_lines):
            removed_line_count += 1
            continue
        kept_lines.append(line)

    cleaned_text = "\n".join(kept_lines)
    truncated = len(cleaned_text) > max_text_chars
    if truncated:
        cleaned_text = cleaned_text[:max_text_chars].rstrip()

    return CleanedText(text=cleaned_text, method=method, original_chars=len(text) if original_chars is None else original_chars, cleaned_chars=len(cleaned_text), original_line_count=len(original_lines), kept_line_count=len(kept_lines), removed_line_count=removed_line_count, truncated=truncated)


def _extract_with_trafilatura(html: str, url: str) -> str:
    if not html.strip():
        return ""
    extracted = extract(html, url=url or None, include_comments=False, include_tables=True, favor_recall=True)
    return extracted or ""


def _normalize_line(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()


def _is_boilerplate_line(line: str, index: int, lines: list[str], line_counts: dict[str, int]) -> bool:
    if line.casefold() in HIGH_CONFIDENCE_CHROME_LINES:
        return True
    if _has_high_link_density(line):
        return True
    # Repeated labels are generally navigation/header/footer fragments. Do not
    # use domain-specific words as a deletion rule.
    if len(line) <= 40 and ":" not in line and line_counts.get(line, 0) >= 2:
        return True
    return _is_structural_chrome_line(line, index, lines)


def _is_repeated_short_line(line: str, seen_short_lines: dict[str, int]) -> bool:
    if len(line) > 30 or ":" in line:
        return False
    count = seen_short_lines.get(line, 0) + 1
    seen_short_lines[line] = count
    return count > 1


def _is_structural_chrome_line(line: str, index: int, lines: list[str]) -> bool:
    """Use position and line shape to identify nav-like edge blocks."""
    if ":" in line or line.startswith("---") or len(line) > 48 or re.search(r"[.!?。！？]", line):
        return False
    words = line.split()
    if len(lines) < 6 or len(words) > 6 or not (index < 8 or index >= max(len(lines) - 8, 0)):
        return False
    neighbors = lines[max(0, index - 2): index + 3]
    short_neighbors = sum(bool(item) and len(item) <= 48 and len(item.split()) <= 6 for item in neighbors)
    return short_neighbors >= 3 and (len(words) <= 3 or bool(re.search(r"\||›|»|→", line)))


def _has_high_link_density(line: str) -> bool:
    """Drop link-only chrome while retaining sentences containing one URL."""
    links = _URL_PATTERN.findall(line)
    if not links:
        return False
    tokens = line.split()
    return len(links) >= 2 or (len(tokens) <= 6 and len(links) / len(tokens) >= 0.5)
