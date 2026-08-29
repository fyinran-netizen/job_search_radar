"""Tool input and output data contracts."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class PageFetchEvidence(BaseModel):
    """Facts observed while collecting a page; no semantic interpretation."""

    status_code: int | None = None
    final_url: str | None = None
    content_type: str = ""
    fetch_method: Literal["file", "http", "browser", "http_then_browser", "unknown"] = "unknown"
    attempts: int = 0
    error: str | None = None


class PageContent(BaseModel):
    """Raw page content plus collection provenance.

    ``title`` and ``text`` remain for compatibility with existing serialized
    artifacts. New collectors should leave them empty; page_processing fills
    them from ``html`` before triage.
    """

    url: str
    source_name: str
    title: str = ""
    text: str = ""
    html: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    fetch_evidence: PageFetchEvidence = Field(default_factory=PageFetchEvidence)

    @property
    def fetch(self) -> PageFetchEvidence:
        """Compatibility accessor for code written during the transition."""
        return self.fetch_evidence


class ToolEvent(BaseModel):
    """One executed tool call."""

    tool_name: str
    input_summary: str
    output_summary: str


