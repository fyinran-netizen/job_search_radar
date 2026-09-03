"""Explicitly configured URL source tool."""
from typing import Any
from pydantic import BaseModel
from job_radar.tools.base import BaseTool
from job_radar.tools.web_search.models import CandidateSource

class ManualSourceTool(BaseTool):
    name = "web_search"
    def __init__(self, sources: list[CandidateSource]) -> None:
        self.sources = sources
    def run(self, payload: BaseModel | dict[str, Any]) -> list[CandidateSource]:
        return self.sources
