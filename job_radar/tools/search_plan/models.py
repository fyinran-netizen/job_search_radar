"""Contracts for search-plan generation."""

from typing import Any

from pydantic import BaseModel, Field, model_validator

from job_radar.profile.models import UserProfile


class SearchPlanLimits(BaseModel):
    max_queries: int = Field(default=6, ge=1)


class SearchPlan(BaseModel):
    target_roles: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    company_types: list[str] = Field(default_factory=list)
    queries: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list, exclude=True)
    cohort_year: int | None = None
    graduation_start: str | None = None
    graduation_end: str | None = None
    cohort_terms: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def migrate_keywords(self) -> "SearchPlan":
        if not self.queries and self.keywords:
            self.queries = list(self.keywords)
        self.keywords = list(self.queries)
        return self



class SearchStrategyContext(BaseModel):
    profile: UserProfile
    round_index: int = Field(default=0, ge=0)
    previous_queries: list[str] = Field(default_factory=list)
    previous_results: list[dict[str, Any]] = Field(default_factory=list)
    limits: SearchPlanLimits = Field(default_factory=SearchPlanLimits)


class SearchPlanToolInput(SearchStrategyContext):
    pass
