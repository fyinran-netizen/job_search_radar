"""Build search strategy objects from a user profile."""

from typing import Protocol

from job_radar.ai.prompt_builder import build_json_prompt
from job_radar.ai.providers.base import AIProvider
from job_radar.ai.providers.codex_cli import CodexCliProvider
from job_radar.ai.skill_loader import load_skill
from job_radar.ai.structured_output import validate_model
from job_radar.models.profile import UserProfile
from job_radar.models.search import SearchPlan


class SearchPlanBuilderProtocol(Protocol):
    """Interface for deterministic or AI-backed search-plan builders."""

    last_source: str
    last_error: str | None

    def build(self, profile: UserProfile) -> SearchPlan:
        """Build a search plan from a complete user profile."""


class SearchPlanBuilder:
    """Deterministic fallback for future AI-backed search strategy generation."""

    last_source = "deterministic"
    last_error: str | None = None

    def build(self, profile: UserProfile) -> SearchPlan:
        """Build a simple search plan from profile preferences."""

        keywords = []
        for role in profile.target_roles:
            keywords.append(f"{role} graduate")
        for location in profile.preferred_locations:
            keywords.append(f"graduate jobs {location}")
        for company_type in profile.preferred_company_types:
            keywords.append(f"{company_type} graduate program")
        return SearchPlan(
            target_roles=profile.target_roles,
            locations=profile.preferred_locations,
            company_types=profile.preferred_company_types,
            keywords=keywords,
        )


class AISearchPlanBuilder:
    """Generate a search plan by applying the search-strategy skill with an AI provider."""

    def __init__(
        self,
        provider: AIProvider,
        skill_name: str = "search-strategy",
        max_keywords: int = 8,
    ) -> None:
        self.provider = provider
        self.skill_name = skill_name
        self.max_keywords = max_keywords
        self.last_source = provider.__class__.__name__
        self.last_error: str | None = None

    def build(self, profile: UserProfile) -> SearchPlan:
        """Build a search plan with a structured AI call."""

        skill = load_skill(self.skill_name)
        prompt = build_json_prompt(
            skill=skill,
            payload={
                "profile": profile.model_dump(),
                "limits": {
                    "max_keywords": self.max_keywords,
                    "max_rounds": 1,
                },
                "previous_queries": [],
            },
            output_model=SearchPlan,
        )
        data = self.provider.generate_json(prompt)
        plan = validate_model(data, SearchPlan)
        return plan.model_copy(update={"keywords": plan.keywords[: self.max_keywords]})


class AutoSearchPlanBuilder:
    """Use local Codex CLI when available, otherwise fall back to deterministic rules."""

    def __init__(
        self,
        codex_provider: CodexCliProvider | None = None,
        fallback_builder: SearchPlanBuilder | None = None,
    ) -> None:
        self.codex_provider = codex_provider or CodexCliProvider()
        self.fallback_builder = fallback_builder or SearchPlanBuilder()
        self.last_source = "deterministic"
        self.last_error: str | None = None

    def build(self, profile: UserProfile) -> SearchPlan:
        """Build a search plan with Codex when possible, with a local fallback."""

        self.last_error = None
        if self.codex_provider.is_available():
            try:
                plan = AISearchPlanBuilder(self.codex_provider).build(profile)
            except Exception as exc:
                self.last_source = "deterministic"
                self.last_error = str(exc)
                return self.fallback_builder.build(profile)
            self.last_source = "codex_cli"
            return plan

        self.last_source = "deterministic"
        self.last_error = "Codex CLI is not installed or not authenticated."
        return self.fallback_builder.build(profile)


def create_search_plan_builder(enable_codex: bool = False) -> SearchPlanBuilderProtocol:
    """Create the default search-plan builder for a runtime."""

    if enable_codex:
        return AutoSearchPlanBuilder()
    return SearchPlanBuilder()
