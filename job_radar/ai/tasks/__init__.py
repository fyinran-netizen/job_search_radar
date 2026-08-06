"""AI-facing tasks."""

from job_radar.ai.tasks.job_extraction import AIJobExtractionClient, AIPageInput, build_ai_page_input
from job_radar.ai.tasks.search_strategy import (
    AISearchPlanBuilder,
    AutoSearchPlanBuilder,
    SearchPlanBuilder,
    create_search_plan_builder,
)

__all__ = [
    "AIJobExtractionClient",
    "AIPageInput",
    "AISearchPlanBuilder",
    "AutoSearchPlanBuilder",
    "SearchPlanBuilder",
    "build_ai_page_input",
    "create_search_plan_builder",
]
