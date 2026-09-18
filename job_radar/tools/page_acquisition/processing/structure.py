"""Extract the small structural envelope needed by downstream analysis."""

from __future__ import annotations

from html.parser import HTMLParser
import re
from urllib.parse import urljoin

from job_radar.tools.page_acquisition.models import PageDocument


class _Parser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title: list[str] = []
        self.text: list[str] = []
        self.links: list[dict[str, str]] = []
        self._in_title = False
        self._skip = 0
        self._href: str | None = None
        self._link_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "template"}:
            self._skip += 1
        if tag == "title": self._in_title = True
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._link_text = []
        if tag in {"br", "p", "div", "li", "tr", "h1", "h2", "h3", "section"}:
            self.text.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "template"} and self._skip: self._skip -= 1
        if tag == "title": self._in_title = False
        if tag == "a" and self._href:
            self.links.append({"href": self._href, "text": " ".join(self._link_text).strip()})
            self._href, self._link_text = None, []

    def handle_data(self, data: str) -> None:
        if self._skip: return
        value = data.strip()
        if not value: return
        if self._in_title: self.title.append(value)
        if self._href: self._link_text.append(value)
        self.text.append(value)


def structure_page(page: PageDocument) -> PageDocument:
    if not page.html: return page
    parser = _Parser()
    try:
        parser.feed(page.html)
        parser.close()
    except Exception:
        return page
    text = "\n".join(re.sub(r"\s+", " ", line).strip() for line in "\n".join(parser.text).splitlines() if line.strip())
    links = [{"href": urljoin(page.url, link["href"]), "text": link["text"]} for link in parser.links]
    return page.model_copy(update={"title": " ".join(parser.title).strip() or page.title, "text": text, "metadata": {**page.metadata, "links": links}})
