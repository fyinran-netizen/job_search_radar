"""Deterministic same-page content recovery for sparse or JS-shell pages."""

import json
import re
from html import unescape
from html.parser import HTMLParser
from typing import Any

from job_radar.tools.page_acquisition.models import PageDocument
from job_radar.tools.page_acquisition.models import (
    PageRecoveryResult,
    RecoverySource,
)


MIN_RECOVERED_CHARS = 300


class _MetadataParser(HTMLParser):
    """Extract metadata and JSON script blocks without browser rendering."""

    def __init__(self) -> None:
        super().__init__()

        self.og_description: str = ""
        self.meta_description: str = ""

        self._script_type: str | None = None
        self._script_buffer: list[str] = []

        self.json_ld_blocks: list[str] = []
        self.json_blocks: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attributes = {
            key.lower(): value or ""
            for key, value in attrs
        }

        if tag.lower() == "meta":
            property_name = (
                attributes.get("property", "")
                .lower()
            )
            name = (
                attributes.get("name", "")
                .lower()
            )
            content = attributes.get(
                "content",
                "",
            )

            if (
                property_name == "og:description"
                and content
            ):
                self.og_description = content

            if (
                name == "description"
                and content
            ):
                self.meta_description = content

        if tag.lower() == "script":
            self._script_type = (
                attributes.get("type", "")
                .lower()
            )
            self._script_buffer = []

    def handle_data(self, data: str) -> None:
        if self._script_type is not None:
            self._script_buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if (
            tag.lower() != "script"
            or self._script_type is None
        ):
            return

        content = "".join(
            self._script_buffer
        ).strip()

        if content:
            if (
                self._script_type
                == "application/ld+json"
            ):
                self.json_ld_blocks.append(
                    content
                )

            elif (
                self._script_type
                == "application/json"
            ):
                self.json_blocks.append(
                    content
                )

        self._script_type = None
        self._script_buffer = []


def recover_page(
    page: PageDocument,
    available_sources: list[RecoverySource],
    min_recovered_chars: int = MIN_RECOVERED_CHARS,
) -> tuple[PageDocument, PageRecoveryResult]:
    """Try deterministic same-page recovery and return an updated page."""

    parser = _parse_metadata(page.html or "")

    attempts: list[RecoverySource] = []
    reasons: list[str] = []

    recovery_order: list[RecoverySource] = [
        "json_ld",
        "og_description",
        "meta_description",
        "embedded_json",
    ]

    for source in recovery_order:
        if source not in available_sources:
            continue

        attempts.append(source)

        recovered_text = _recover_from_source(
            source,
            page,
            parser,
        )

        recovered_text = _normalize_recovered_text(
            recovered_text
        )

        if (
            len(recovered_text)
            >= min_recovered_chars
        ):
            updated_metadata = {
                **page.metadata,
                "recovery": {
                    "success": True,
                    "source": source,
                    "recovered_chars": len(
                        recovered_text
                    ),
                },
            }

            recovered_page = page.model_copy(
                update={
                    "text": recovered_text,
                    "metadata": updated_metadata,
                }
            )

            return (
                recovered_page,
                PageRecoveryResult(
                    success=True,
                    source=source,
                    text=recovered_text,
                    attempted_sources=attempts,
                    reasons=[
                        f"recovered_from_{source}"
                    ],
                    evidence={
                        "original_text_chars": len(
                            page.text.strip()
                        ),
                        "recovered_text_chars": len(
                            recovered_text
                        ),
                    },
                ),
            )

        reasons.append(
            f"{source}_insufficient: "
            f"{len(recovered_text)} chars"
        )

    return (
        page,
        PageRecoveryResult(
            success=False,
            attempted_sources=attempts,
            reasons=(
                reasons
                or [
                    "no_deterministic_recovery_source_succeeded"
                ]
            ),
            evidence={
                "original_text_chars": len(
                    page.text.strip()
                ),
                "html_chars": len(
                    page.html or ""
                ),
            },
        ),
    )


def _recover_from_source(
    source: RecoverySource,
    page: PageDocument,
    parser: _MetadataParser,
) -> str:
    if source == "json_ld":
        return _recover_from_json_ld(
            parser.json_ld_blocks
        )

    if source == "og_description":
        return unescape(
            parser.og_description
        )

    if source == "meta_description":
        return unescape(
            parser.meta_description
        )

    if source == "embedded_json":
        return _recover_from_embedded_json(
            page.html or "",
            parser.json_blocks,
        )

    return ""


def _recover_from_json_ld(
    blocks: list[str],
) -> str:
    candidates: list[str] = []

    for block in blocks:
        try:
            payload = json.loads(block)
        except json.JSONDecodeError:
            continue

        for item in _flatten_json_ld(payload):
            if not isinstance(item, dict):
                continue

            item_type = item.get("@type")

            if isinstance(item_type, list):
                normalized_types = {
                    str(value).lower()
                    for value in item_type
                }
            else:
                normalized_types = {
                    str(item_type).lower()
                }

            if (
                "jobposting"
                not in normalized_types
            ):
                continue

            parts = [
                item.get("title"),
                item.get("description"),
                _json_value_to_text(
                    item.get("qualifications")
                ),
                _json_value_to_text(
                    item.get("responsibilities")
                ),
                _json_value_to_text(
                    item.get("skills")
                ),
            ]

            text = "\n".join(
                str(part)
                for part in parts
                if part
            )

            if text:
                candidates.append(text)

    if not candidates:
        return ""

    return max(
        candidates,
        key=len,
    )


def _flatten_json_ld(
    payload: Any,
) -> list[Any]:
    if isinstance(payload, list):
        return payload

    if not isinstance(payload, dict):
        return []

    graph = payload.get("@graph")

    if isinstance(graph, list):
        return graph

    return [payload]


def _recover_from_embedded_json(
    html: str,
    script_blocks: list[str],
) -> str:
    candidates: list[str] = []

    for block in script_blocks:
        try:
            payload = json.loads(block)
        except json.JSONDecodeError:
            continue

        candidates.extend(
            _collect_long_text_values(
                payload
            )
        )

    patterns = [
        r'"description"\s*:\s*"((?:\\.|[^"\\])*)"',
        r'"jobDescription"\s*:\s*"((?:\\.|[^"\\])*)"',
        r'"content"\s*:\s*"((?:\\.|[^"\\])*)"',
    ]

    for pattern in patterns:
        for match in re.findall(
            pattern,
            html,
            flags=re.I,
        ):
            candidates.append(
                _decode_json_string(match)
            )

    if not candidates:
        return ""

    return max(
        candidates,
        key=len,
    )


def _collect_long_text_values(
    value: Any,
) -> list[str]:
    results: list[str] = []

    if isinstance(value, dict):
        for key, item in value.items():
            key_lower = str(key).lower()

            if (
                key_lower
                in {
                    "description",
                    "jobdescription",
                    "responsibilities",
                    "qualifications",
                    "requirements",
                    "content",
                }
                and isinstance(item, str)
                and len(item) >= 100
            ):
                results.append(item)

            results.extend(
                _collect_long_text_values(item)
            )

    elif isinstance(value, list):
        for item in value:
            results.extend(
                _collect_long_text_values(item)
            )

    return results


def _json_value_to_text(
    value: Any,
) -> str:
    if isinstance(value, str):
        return value

    if isinstance(value, list):
        return "\n".join(
            str(item)
            for item in value
            if item
        )

    return ""


def _decode_json_string(
    value: str,
) -> str:
    try:
        return json.loads(
            f'"{value}"'
        )
    except json.JSONDecodeError:
        return value


def _normalize_recovered_text(
    text: str,
) -> str:
    text = unescape(text)

    text = re.sub(
        r"<[^>]+>",
        " ",
        text,
    )

    text = re.sub(
        r"[ \t]+",
        " ",
        text,
    )

    text = re.sub(
        r"\n\s*\n+",
        "\n",
        text,
    )

    return text.strip()


def _parse_metadata(
    html: str,
) -> _MetadataParser:
    parser = _MetadataParser()

    if html.strip():
        try:
            parser.feed(html)
        except Exception:
            pass

    return parser
