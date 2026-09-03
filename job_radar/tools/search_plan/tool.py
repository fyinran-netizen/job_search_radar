"""Agent Tool wrapper for deterministic search planning."""

from typing import Any

from pydantic import BaseModel

from job_radar.tools.base import BaseTool
from job_radar.tools.search_plan.builder import SearchPlanBuilder
from job_radar.tools.search_plan.models import SearchPlan, SearchPlanToolInput


class BuildSearchPlanTool(BaseTool):
    name = "build_search_plan"

    def __init__(self, builder: SearchPlanBuilder | None = None) -> None:
        self.builder = builder or SearchPlanBuilder()

    def run(self, payload: BaseModel | dict[str, Any]) -> SearchPlan:
        context = payload if isinstance(payload, SearchPlanToolInput) else SearchPlanToolInput.model_validate(payload)
        return self.builder.build_from_context(context)
