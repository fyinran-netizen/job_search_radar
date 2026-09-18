"""Technical checks only; no job or relevance classification."""

from __future__ import annotations

import re


def inspect_content(html: str, *, status_code: int | None = None, content_type: str = "", max_response_bytes: int = 2_000_000) -> list[str]:
    reasons: list[str] = []
    if status_code is not None and not 200 <= status_code < 300:
        reasons.append(f"http_status_{status_code}")
    if not html.strip():
        reasons.append("empty_page")
        return reasons
    if len(html.encode("utf-8")) > max_response_bytes:
        reasons.append("response_too_large")
    lowered = html.lower()
    visible = re.sub(r"<script\b[^>]*>.*?</script\s*>", " ", html, flags=re.I | re.S)
    visible = re.sub(r"<[^>]+>", " ", visible)
    visible = re.sub(r"\s+", " ", visible).strip()
    if "application/json" in content_type.lower() or "application/pdf" in content_type.lower() or "image/" in content_type.lower():
        reasons.append("non_html_resource")
    if "\x00" in html or sum(ord(char) < 9 for char in html) > 3 or "�" in html:
        reasons.append("binary_or_mojibake")
    shell = bool(re.search(r"<(?:div|main)[^>]+(?:id|class)=[\"'][^\"']*(?:app|root|__next)[^\"']*[\"'][^>]*>\s*</", lowered))
    scripts = bool(re.search(r"<script[^>]+src=[\"'][^\"']+\.js(?:[\"']|\?)", lowered))
    if shell or (scripts and len(visible) < 200):
        reasons.append("javascript_shell")
    if re.search(r"access denied|forbidden|captcha|verify you are human|unusual traffic", visible, re.I):
        reasons.append("access_interstitial")
    return reasons
