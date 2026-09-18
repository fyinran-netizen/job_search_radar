"""Recover content embedded in an already collected document.

This is deliberately separate from transport retries and browser rendering.
"""

from __future__ import annotations

import json
import re
from html import unescape
from html.parser import HTMLParser

from job_radar.tools.page_acquisition.models import PageDocument, PageRecoveryResult, RecoverySource

MIN_RECOVERED_CHARS = 300


class _EmbeddedContentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(); self.og = ""; self.meta = ""; self._type = ""; self._data: list[str] = []
        self.json_ld: list[str] = []; self.json_blocks: list[str] = []
    def handle_starttag(self, tag, attrs):
        values = {key.lower(): value or "" for key, value in attrs}
        if tag.lower() == "meta":
            if values.get("property", "").lower() == "og:description": self.og = values.get("content", "")
            if values.get("name", "").lower() == "description": self.meta = values.get("content", "")
        if tag.lower() == "script": self._type, self._data = values.get("type", "").lower(), []
    def handle_data(self, data):
        if self._type: self._data.append(data)
    def handle_endtag(self, tag):
        if tag.lower() != "script" or not self._type: return
        value = "".join(self._data).strip()
        if value and self._type == "application/ld+json": self.json_ld.append(value)
        if value and self._type == "application/json": self.json_blocks.append(value)
        self._type, self._data = "", []


def recover_page(page: PageDocument, available_sources: list[RecoverySource] | None = None, min_recovered_chars: int = MIN_RECOVERED_CHARS) -> tuple[PageDocument, PageRecoveryResult]:
    parser = _EmbeddedContentParser()
    try: parser.feed(page.html or "")
    except Exception: pass
    available = available_sources or detect_content_sources(page.html or "", page.metadata.get("links", []))
    attempts: list[RecoverySource] = []; reasons: list[str] = []
    for source in ("json_ld", "og_description", "meta_description", "embedded_json"):
        if source not in available: continue
        attempts.append(source); text = _normalize(_recover(source, page.html or "", parser))
        if len(text) >= min_recovered_chars:
            updated = page.model_copy(update={"text": text, "metadata": {**page.metadata, "recovery": {"success": True, "source": source, "recovered_chars": len(text)}}})
            return updated, PageRecoveryResult(success=True, source=source, text=text, attempted_sources=attempts, reasons=[f"recovered_from_{source}"], evidence={"original_text_chars": len(page.text), "recovered_text_chars": len(text)})
        reasons.append(f"{source}_insufficient: {len(text)} chars")
    return page, PageRecoveryResult(attempted_sources=attempts, reasons=reasons or ["no_deterministic_recovery_source_succeeded"], evidence={"original_text_chars": len(page.text), "html_chars": len(page.html or "")})


def detect_content_sources(html: str, links: object = ()) -> list[RecoverySource]:
    found: list[RecoverySource] = []
    if re.search(r"<script[^>]+type=[\"']application/ld\+json", html, re.I): found.append("json_ld")
    if re.search(r"<meta[^>]+property=[\"']og:description", html, re.I): found.append("og_description")
    if re.search(r"<meta[^>]+name=[\"']description", html, re.I): found.append("meta_description")
    if re.search(r"(?:__INITIAL_STATE__|__NEXT_DATA__|application/json)", html, re.I): found.append("embedded_json")
    return found


def _recover(source, html, parser):
    if source == "og_description": return unescape(parser.og)
    if source == "meta_description": return unescape(parser.meta)
    if source == "json_ld":
        values = []
        for block in parser.json_ld:
            try: payload = json.loads(block)
            except json.JSONDecodeError: continue
            items = payload if isinstance(payload, list) else payload.get("@graph", [payload]) if isinstance(payload, dict) else []
            for item in items:
                if isinstance(item, dict) and "jobposting" in str(item.get("@type", "")).lower():
                    values.append("\n".join(str(item.get(key, "")) for key in ("title", "description", "qualifications", "responsibilities", "skills") if item.get(key)))
        return max(values, key=len, default="")
    values = []
    for block in parser.json_blocks:
        try: payload = json.loads(block)
        except json.JSONDecodeError: continue
        values.extend(_long_values(payload))
    for match in re.findall(r'"(?:description|jobDescription|content)"\s*:\s*"((?:\\.|[^"\\])*)"', html, re.I):
        try: values.append(json.loads(f'"{match}"'))
        except json.JSONDecodeError: values.append(match)
    return max(values, key=len, default="")


def _long_values(value):
    if isinstance(value, dict):
        result = [item for key, item in value.items() if str(key).lower() in {"description", "jobdescription", "responsibilities", "qualifications", "requirements", "content"} and isinstance(item, str) and len(item) >= 100]
        return result + [item for child in value.values() for item in _long_values(child)]
    if isinstance(value, list): return [item for child in value for item in _long_values(child)]
    return []


def _normalize(text: str) -> str:
    return re.sub(r"\n\s*\n+", "\n", re.sub(r"[ \t]+", " ", re.sub(r"<[^>]+>", " ", unescape(text)))).strip()
