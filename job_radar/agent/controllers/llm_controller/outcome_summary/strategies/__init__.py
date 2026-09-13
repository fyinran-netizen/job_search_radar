"""Dedicated outcome summary strategies for canonical actions."""

from job_radar.agent.controllers.llm_controller.outcome_summary.strategies.analyze_page import summarize as analyze_page
from job_radar.agent.controllers.llm_controller.outcome_summary.strategies.acquire_page import summarize as acquire_page
from job_radar.agent.controllers.llm_controller.outcome_summary.strategies.build_search_plan import summarize as build_search_plan
from job_radar.agent.controllers.llm_controller.outcome_summary.strategies.job_extraction import summarize as job_extraction
from job_radar.agent.controllers.llm_controller.outcome_summary.strategies.job_understanding import summarize as job_understanding
from job_radar.agent.controllers.llm_controller.outcome_summary.strategies.match_analysis import summarize as match_analysis
from job_radar.agent.controllers.llm_controller.outcome_summary.strategies.stop import summarize as stop
from job_radar.agent.controllers.llm_controller.outcome_summary.strategies.web_search import summarize as web_search

STRATEGIES = {
    "build_search_plan": build_search_plan,
    "web_search": web_search,
    "acquire_page": acquire_page,
    "analyze_page": analyze_page,
    "job_extraction": job_extraction,
    "job_understanding": job_understanding,
    "match_analysis": match_analysis,
    "stop": stop,
}

__all__ = ["STRATEGIES"]
