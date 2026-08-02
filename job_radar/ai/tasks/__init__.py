"""AI-facing tasks.

Current implementations are deterministic so the project works without a Codex
CLI or model API. Future Codex-backed tasks should keep the same model outputs.
"""

from job_radar.ai.tasks.profile_completeness import ProfileCompletenessChecker
from job_radar.ai.tasks.search_strategy import SearchPlanBuilder

__all__ = ["ProfileCompletenessChecker", "SearchPlanBuilder"]
