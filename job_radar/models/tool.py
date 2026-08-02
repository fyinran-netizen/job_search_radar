"""Tool input and output data contracts."""

from typing import Any

from pydantic import BaseModel, Field


class PageContent(BaseModel):
    """Fetched page content returned by a page collection tool."""

    url: str
    source_name: str
    title: str
    text: str
    html: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolEvent(BaseModel):
    """One executed tool call."""

    tool_name: str
    input_summary: str
    output_summary: str
