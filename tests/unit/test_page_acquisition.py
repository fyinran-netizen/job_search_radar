import gzip
import json
import zlib

import pytest

from job_radar.tools.page_acquisition.pipeline import PageAcquisitionPipeline
from job_radar.tools.page_acquisition.models import PageDocument
from job_radar.tools.page_acquisition.processing.decoding import DecodeError, decode_response
from job_radar.tools.page_acquisition.recovery.content import recover_page
from job_radar.tools.web_search.models import CandidateSource


def source():
    return CandidateSource(url="https://example.test/page", title="Source title", source_name="Example")


HttpPageTool = PageAcquisitionPipeline


def test_decoding_gzip_deflate_and_charset():
    body = '<html><head><meta charset="iso-8859-1"><title>Café</title></head><body>Résumé</body></html>'.encode("iso-8859-1")
    assert "Café" in decode_response(gzip.compress(body), {"Content-Encoding": "gzip"}).text
    assert "Résumé" in decode_response(zlib.compress(body), {"Content-Encoding": "deflate", "Content-Type": "text/html; charset=iso-8859-1"}).text


def test_bad_compression_is_not_replaced_with_mojibake():
    with pytest.raises(DecodeError):
        decode_response(b"not gzip", {"Content-Encoding": "gzip"})


def test_pipeline_extracts_title_visible_text_and_absolute_hrefs(monkeypatch):
    class Response:
        raw_bytes = b'<html><title>Hello</title><script>hidden()</script><a href="/apply">Apply</a><p>Visible text</p></html>'
        status_code = 200; final_url = "https://example.test/page"; headers = {"Content-Type": "text/html"}; attempts = 1; fetch_method = "http"
    tool = HttpPageTool(browser_fallback=lambda _url: "<html><p>browser</p></html>")
    monkeypatch.setattr(tool.http, "fetch", lambda _url: Response())
    page = tool.run(source())
    assert page.title == "Hello"
    assert "hidden" not in page.text and "Visible text" in page.text
    assert page.metadata["links"] == [{"href": "https://example.test/apply", "text": "Apply"}]


def test_js_shell_uses_browser_fallback(monkeypatch):
    class Response:
        raw_bytes = b'<html><body><div id="app"></div><script src="app.js"></script></body></html>'
        status_code = 200; final_url = "https://example.test/page"; headers = {"Content-Type": "text/html"}; attempts = 1; fetch_method = "http"
    tool = HttpPageTool(browser_fallback=lambda _url: "<html><title>Rendered</title><p>Loaded content</p></html>")
    monkeypatch.setattr(tool.http, "fetch", lambda _url: Response())
    page = tool.run(source())
    assert page.title == "Rendered"
    assert page.fetch_evidence.fetch_method == "browser"


def test_bad_compression_enters_browser_fallback(monkeypatch):
    class Response:
        raw_bytes = b"broken"
        status_code = 200; final_url = "https://example.test/page"; headers = {"Content-Type": "text/html", "Content-Encoding": "gzip"}; attempts = 1; fetch_method = "http"
    tool = HttpPageTool(browser_fallback=lambda _url: "<html><title>Recovered</title><p>Rendered after decode failure</p></html>")
    monkeypatch.setattr(tool.http, "fetch", lambda _url: Response())
    page = tool.run(source())
    assert page.title == "Recovered"
    assert page.fetch_evidence.fetch_method == "browser"


def test_oversized_http_response_is_reported_and_can_fallback(monkeypatch):
    class Response:
        raw_bytes = b"x" * 20
        status_code = 200; final_url = "https://example.test/page"; headers = {"Content-Type": "text/html"}; attempts = 1; fetch_method = "http"
    tool = HttpPageTool(max_response_bytes=10, browser_fallback=lambda _url: "<html><p>small rendered page</p></html>")
    monkeypatch.setattr(tool.http, "fetch", lambda _url: Response())
    page = tool.run(source())
    assert page.fetch_evidence.fetch_method == "browser"
    assert "response_too_large" in page.metadata["technical_checks"]


def test_recovery_reads_json_ld_without_mixing_transport():
    description = "A detailed role description with responsibilities and qualifications. " * 10
    payload = json.dumps({"@type": "JobPosting", "title": "Analyst", "description": description})
    page = PageDocument(url=source().url, source_name="Example", html=f'<script type="application/ld+json">{payload}</script>')
    recovered, result = recover_page(page)
    assert result.success
    assert "detailed role description" in recovered.text
