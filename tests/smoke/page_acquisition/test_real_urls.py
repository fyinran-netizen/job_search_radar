"""Real-network smoke checks for the complete page acquisition pipeline.

Run explicitly with: ``uv run pytest tests/smoke/page_acquisition -q``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from job_radar.tools.page_acquisition.models import PageDocument
from job_radar.tools.page_acquisition.pipeline import PageAcquisitionPipeline
from job_radar.tools.web_search.models import CandidateSource


OUTPUT_DIR = Path(__file__).parents[2] / "output" / "page_acquisition"

pytestmark = pytest.mark.skipif(
    os.environ.get("JOB_RADAR_RUN_REAL_SMOKE") != "1",
    reason="real-network smoke tests require JOB_RADAR_RUN_REAL_SMOKE=1",
)

CASES = [
    pytest.param(
        "python_jobs",
        "https://www.python.org/jobs/",
        id="python-jobs",
    ),
    pytest.param(
        "httpbin_gzip",
        "https://httpbin.org/gzip",
        id="httpbin-gzip",
    ),
    pytest.param(
        "httpbin_deflate",
        "https://httpbin.org/deflate",
        id="httpbin-deflate",
    ),
    pytest.param(
        "httpbin_redirect",
        "https://httpbin.org/redirect/2",
        id="httpbin-redirect",
    ),
    pytest.param(
        "httpbin_png",
        "https://httpbin.org/image/png",
        id="httpbin-png",
    ),
    pytest.param(
        "quotes_js",
        "https://quotes.toscrape.com/js/",
        id="quotes-js",
    ),
]


@pytest.mark.parametrize("case_name,url", CASES)
def test_real_url_acquisition(case_name: str, url: str) -> None:
    """Acquire one real URL, persist diagnostics, then assert its route."""

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    source = CandidateSource(url=url, title=case_name, source_name="real-url-smoke")
    pipeline = PageAcquisitionPipeline(timeout_seconds=15, retries=1)

    try:
        page = pipeline.run(source)
        result = _result(page, url)
    except Exception as exc:  # Keep a durable diagnostic even for transport failures.
        result = {
            "input_url": url,
            "success": False,
            "fetch_method": None,
            "status_code": None,
            "final_url": None,
            "content_type": None,
            "content_encoding": None,
            "title": "",
            "html_length": 0,
            "text_length": 0,
            "links_count": 0,
            "text_preview": "",
            "links_preview": [],
            "fetch_error": f"{type(exc).__name__}: {exc}",
            "browser_fallback": False,
        }

    output_file = OUTPUT_DIR / f"{case_name}.json"
    output_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    _assert_expected_route(case_name, result)


def _result(page: PageDocument, input_url: str) -> dict[str, object]:
    evidence = page.fetch_evidence
    metadata = page.metadata
    content_encoding = metadata.get("content_encoding")
    links = metadata.get("links", [])
    links = links if isinstance(links, list) else []
    return {
        "input_url": input_url,
        "success": not bool(evidence.error),
        "fetch_method": evidence.fetch_method,
        "status_code": evidence.status_code,
        "final_url": evidence.final_url,
        "content_type": evidence.content_type,
        "content_encoding": content_encoding,
        "title": page.title,
        "html_length": len(page.html),
        "text_length": len(page.text),
        "links_count": len(links),
        "text_preview": page.text[:1000],
        "links_preview": links[:5],
        "fetch_error": evidence.error,
        "browser_fallback": evidence.fetch_method in {"browser", "http_then_browser"},
        "technical_checks": metadata.get("technical_checks", []),
        "resource_kind": metadata.get("resource_kind"),
    }


def _assert_expected_route(case_name: str, result: dict[str, object]) -> None:
    error = result["fetch_error"]
    assert not error, f"{case_name} acquisition failed; see output JSON: {error}"
    assert result["status_code"] is not None and 200 <= result["status_code"] < 300

    if case_name == "python_jobs":
        assert result["html_length"] > 0
        assert result["text_length"] > 0
        assert "�" not in result["text_preview"]
    elif case_name in {"httpbin_gzip", "httpbin_deflate"}:
        assert result["html_length"] > 0
        assert "�" not in result["text_preview"]
    elif case_name == "httpbin_redirect":
        assert result["final_url"] and result["final_url"] != result["input_url"]
    elif case_name == "httpbin_png":
        assert result["success"] is True
        assert result["fetch_method"] == "http"
        assert str(result["content_type"]).lower().startswith("image/png")
        assert result["resource_kind"] == "image"
        assert result["browser_fallback"] is False
        assert result["status_code"] == 200
        assert result["title"] == ""
        assert result["html_length"] == 0
        assert result["text_length"] == 0
        assert result["links_count"] == 0
    elif case_name == "quotes_js":
        assert result["fetch_method"] == "browser"
        assert result["html_length"] > 0
        assert result["text_length"] > 0
        assert result["links_count"] > 0
