"""HTTP page collection tool for manually configured URLs."""

from html.parser import HTMLParser
from pathlib import Path
import re
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.request import Request, url2pathname, urlopen

from pydantic import BaseModel

from job_radar.agents.models import CandidateSource, PageContent
from job_radar.tools.base import BaseTool


class _HTMLTextParser(HTMLParser):
    """Extract title, visible text, and links from simple HTML."""

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
        if tag in {"script", "style", "noscript"}:
            self.skip_depth += 1
        if tag == "title":
            self.in_title = True
        if tag == "a":
            attrs_dict = dict(attrs)
            self.current_href = attrs_dict.get("href")
            self.current_link_text = []
        if tag in {"br", "p", "div", "li", "tr", "h1", "h2", "h3", "section"}:
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self.skip_depth:
            self.skip_depth -= 1
        if tag == "title":
            self.in_title = False
        if tag == "a" and self.current_href:
            self.links.append(
                {
                    "href": self.current_href,
                    "text": " ".join(self.current_link_text).strip(),
                }
            )
            self.current_href = None
            self.current_link_text = []

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        text = data.strip()
        if not text:
            return
        if self.in_title:
            self.title_parts.append(text)
        if self.current_href:
            self.current_link_text.append(text)
        self.text_parts.append(text)

    @property
    def title(self) -> str:
        return " ".join(self.title_parts).strip()

    @property
    def text(self) -> str:
        raw = "\n".join(self.text_parts)
        lines = [re.sub(r"\s+", " ", line).strip() for line in raw.splitlines()]
        return "\n".join(line for line in lines if line)


class HttpPageCollectorTool(BaseTool):
    """Fetch a URL and return visible page content."""

    name = "collect_page"

    def __init__(self, timeout_seconds: int = 20) -> None:
        self.timeout_seconds = timeout_seconds

    def run(self, payload: BaseModel | dict[str, Any]) -> PageContent:
        """Fetch HTML for a candidate source and convert it to page content."""

        source = payload if isinstance(payload, CandidateSource) else CandidateSource.model_validate(payload)
        html = self._read_url(source.url)
        parser = _HTMLTextParser()
        parser.feed(html)
        parser.close()
        title = parser.title or source.title
        return PageContent(
            url=source.url,
            source_name=source.source_name,
            title=title,
            text=parser.text,
            html=html,
            metadata={
                "company_name": source.company_name,
                "company_type": source.company_type,
                "is_official": source.is_official,
                "links": [
                    {"href": urljoin(source.url, link["href"]), "text": link["text"]}
                    for link in parser.links
                ],
            },
        )

    def _read_url(self, url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme == "file":
            return Path(url2pathname(parsed.path)).read_text(encoding="utf-8")
        request = Request(
            url,
            headers={
                "User-Agent": "JobRadar/0.1 local research tool",
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            raw = response.read()
            content_type = response.headers.get("Content-Type", "")
        encoding = self._detect_encoding(content_type, raw)
        return raw.decode(encoding, errors="replace")

    @staticmethod
    def _detect_encoding(content_type: str, raw: bytes) -> str:
        header_match = re.search(r"charset=([\w-]+)", content_type, re.I)
        if header_match:
            return header_match.group(1)
        head = raw[:4096].decode("ascii", errors="ignore")
        meta_match = re.search(r"charset=['\"]?([\w-]+)", head, re.I)
        if meta_match:
            return meta_match.group(1)
        return "utf-8"
