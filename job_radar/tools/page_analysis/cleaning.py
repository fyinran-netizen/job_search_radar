"""Conservative text cleaning for technically readable pages."""

import re
from html.parser import HTMLParser
from urllib.parse import urljoin

from pydantic import BaseModel
from trafilatura import extract
from job_radar.tools.page_acquisition.models import PageDocument


class _HTMLContentParser(HTMLParser):
    """Parse raw collected HTML into processing-time content signals."""

    def __init__(self) -> None:
        super().__init__()
        self.skip_depth = 0
        self.in_title = False
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.links: list[dict[str, str]] = []
        self.current_href: str | None = None
        self.current_link_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript"}:
            self.skip_depth += 1
        if tag == "title":
            self.in_title = True
        if tag == "a":
            values = dict(attrs)
            self.current_href = values.get("href")
            self.current_link_text = []
        if tag in {"br", "p", "div", "li", "tr", "h1", "h2", "h3", "section"}:
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript"} and self.skip_depth:
            self.skip_depth -= 1
        if tag == "title":
            self.in_title = False
        if tag == "a" and self.current_href:
            self.links.append({"href": self.current_href, "text": " ".join(self.current_link_text).strip()})
            self.current_href = None
            self.current_link_text = []

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        value = data.strip()
        if not value:
            return
        if self.in_title:
            self.title_parts.append(value)
        if self.current_href:
            self.current_link_text.append(value)
        self.text_parts.append(value)


def parse_acquired_page(page: PageDocument) -> PageDocument:
    """Derive title, visible text, and links from raw collected content."""
    if not page.html:
        return page
    parser = _HTMLContentParser()
    try:
        parser.feed(page.html)
        parser.close()
    except Exception:
        return page
    raw_text = "\n".join(parser.text_parts)
    text = "\n".join(re.sub(r"\s+", " ", line).strip() for line in raw_text.splitlines() if line.strip())
    metadata = {**page.metadata, "links": [{"href": urljoin(page.url, item["href"]), "text": item["text"]} for item in parser.links]}
    return page.model_copy(update={"title": " ".join(parser.title_parts).strip() or page.title, "text": text, "metadata": metadata})


BOILERPLATE_EXACT_LINES = {
    "首页",
    "主页",
    "学生",
    "用人单位",
    "校友",
    "登录",
    "退出",
    "安全退出",
    "进入功能区",
    "分享至",
    "联系我们",
    "联系方式",
    "关于我们",
    "more+",
    "image",
    "收藏",
    "我是学生",
    "我是单位",
    "我是教师",
    "学生服务",
    "单位服务",
    "了解学校",
    "发布信息",
    "招聘信息",
    "招聘会信息",
    "新闻公告",
    "重要通知",
    "工作动态",
    "活动预告",
    "职业测评",
    "生涯咨询",
    "创业指导",
    "就业政策",
    "就业手续",
    "文件下载",
    "办事大厅",
    "意见反馈",
    "浏览职位",
    "招聘观察",
    "购买与订阅",
}

BOILERPLATE_CONTAINS = [
    "抵制招聘诈骗",
    "以任何理由索取财物",
    "牛客安全提示",
    "浏览次数",
    "就业管理系统登录",
]


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


def clean_page_text(
    html: str,
    fallback_text: str,
    url: str = "",
    max_text_chars: int = 12000,
    min_extracted_chars: int = 300,
) -> CleanedText:
    """Extract main content and fall back to collected or recovered text."""

    extracted_text = _extract_with_trafilatura(
        html,
        url,
    )

    if (
        extracted_text
        and len(extracted_text.strip())
        >= min_extracted_chars
    ):
        return clean_visible_text(
            extracted_text,
            max_text_chars=max_text_chars,
            method="trafilatura",
            original_chars=len(
                fallback_text
            ),
        )

    return clean_visible_text(
        fallback_text,
        max_text_chars=max_text_chars,
        method="fallback_text",
        original_chars=len(
            fallback_text
        ),
    )


def clean_visible_text(
    text: str,
    max_text_chars: int = 12000,
    method: str = "fallback_text",
    original_chars: int | None = None,
) -> CleanedText:
    """Remove obvious page chrome while preserving useful job context."""

    original_lines = text.splitlines()

    kept_lines: list[str] = []
    seen_short_lines: dict[str, int] = {}

    removed_line_count = 0

    for line in original_lines:
        cleaned_line = _normalize_line(
            line
        )

        if not cleaned_line:
            removed_line_count += 1
            continue

        if _is_boilerplate_line(
            cleaned_line
        ):
            removed_line_count += 1
            continue

        if _is_repeated_short_line(
            cleaned_line,
            seen_short_lines,
        ):
            removed_line_count += 1
            continue

        kept_lines.append(
            cleaned_line
        )

    cleaned_text = "\n".join(
        kept_lines
    )

    truncated = (
        len(cleaned_text)
        > max_text_chars
    )

    if truncated:
        cleaned_text = (
            cleaned_text[
                :max_text_chars
            ].rstrip()
        )

    return CleanedText(
        text=cleaned_text,
        method=method,
        original_chars=(
            len(text)
            if original_chars is None
            else original_chars
        ),
        cleaned_chars=len(
            cleaned_text
        ),
        original_line_count=len(
            original_lines
        ),
        kept_line_count=len(
            kept_lines
        ),
        removed_line_count=(
            removed_line_count
        ),
        truncated=truncated,
    )


def _extract_with_trafilatura(
    html: str,
    url: str,
) -> str:
    if not html.strip():
        return ""

    extracted = extract(
        html,
        url=url or None,
        include_comments=False,
        include_tables=True,
        favor_recall=True,
    )

    return extracted or ""


def _normalize_line(
    line: str,
) -> str:
    return re.sub(
        r"\s+",
        " ",
        line,
    ).strip()


def _is_boilerplate_line(
    line: str,
) -> bool:
    lowered = line.lower()

    if lowered in BOILERPLATE_EXACT_LINES:
        return True

    return any(
        marker.lower() in lowered
        for marker
        in BOILERPLATE_CONTAINS
    )


def _is_repeated_short_line(
    line: str,
    seen_short_lines: dict[str, int],
) -> bool:
    if len(line) > 30:
        return False

    count = (
        seen_short_lines.get(
            line,
            0,
        )
        + 1
    )

    seen_short_lines[line] = count

    return count > 2
