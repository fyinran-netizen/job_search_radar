"""Tool input and output data contracts."""

from typing import Any, Literal

from pydantic import BaseModel, Field


PageRouteStatus = Literal["rejected", "recoverable", "readable"]
RecoverySource = Literal[
    "json_ld", "og_description", "meta_description", "embedded_json", "important_links"
]


class PageTechnicalRoute(BaseModel):
    """Acquisition-time technical route and evidence."""

    status: PageRouteStatus
    reason_codes: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    text_length: int = 0
    html_length: int = 0
    recovery_sources: list[RecoverySource] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)


class PageRecoveryResult(BaseModel):
    """Result of deterministic content recovery during acquisition."""

    success: bool = False
    source: RecoverySource | None = None
    text: str = ""
    attempted_sources: list[RecoverySource] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)


class RejectedPage(BaseModel):
    """A page rejected by deterministic acquisition or analysis quality checks."""

    url: str
    source_name: str
    title: str
    reasons: list[str] = Field(default_factory=list)
    text_length: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class PageFetchEvidence(BaseModel):
    """Facts observed while collecting a page; no semantic interpretation."""

    status_code: int | None = None
    final_url: str | None = None
    content_type: str = ""
    fetch_method: Literal["file", "http", "browser", "http_then_browser", "unknown"] = "unknown"
    attempts: int = 0
    error: str | None = None


class PageDocument(BaseModel):
    """Acquired page content plus acquisition provenance.

    ``title`` and ``text`` are populated when acquisition can recover or
    directly provide usable content; analysis may further clean them.
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


