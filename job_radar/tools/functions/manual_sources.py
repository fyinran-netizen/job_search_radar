"""Manual source tool used before real search APIs are connected."""

from typing import Any

from pydantic import BaseModel

from job_radar.models.search import CandidateSource
from job_radar.tools.base import BaseTool


class ManualSourceTool(BaseTool):
    """Return configured candidate sources instead of calling a search API."""

    name = "web_search"

    def __init__(self, sources: list[CandidateSource]) -> None:
        self.sources = sources

    def run(self, payload: BaseModel | dict[str, Any]) -> list[CandidateSource]:
        """Return manually configured sources."""

        return self.sources
