"""Deterministic, bounded search-plan generation."""

from typing import Protocol

from job_radar.profile.cohort import infer_graduation_cohort
from job_radar.profile.models import UserProfile
from job_radar.tools.search_plan.models import SearchPlan, SearchPlanLimits, SearchStrategyContext


class SearchPlanBuilderProtocol(Protocol):
    def build(
        self,
        profile: UserProfile,
        search_round_count: int = 0,
        previous_queries: list[str] | None = None,
        previous_results: list[dict] | None = None,
        limits: SearchPlanLimits | None = None,
    ) -> SearchPlan: ...


class SearchPlanBuilder:
    """Build role-led queries with deterministic round variation."""

    last_source = "deterministic"
    last_error = None

    def build(
        self,
        profile: UserProfile,
        search_round_count: int = 0,
        previous_queries: list[str] | None = None,
        previous_results: list[dict] | None = None,
        limits: SearchPlanLimits | None = None,
    ) -> SearchPlan:
        del previous_results
        previous = {q.casefold().strip() for q in (previous_queries or [])}
        cohort = infer_graduation_cohort(profile.graduation_date)
        cohort_signal = (
            cohort.search_terms[search_round_count % len(cohort.search_terms)]
            if cohort else "graduate"
        )
        locations = profile.preferred_locations or ["Australia"]
        company_types = profile.preferred_company_types or ["employer"]
        detail_signals = ["careers apply", "job description requirements", "graduate program"]
        queries: list[str] = []
        for offset, role in enumerate(profile.target_roles or ["graduate"]):
            location = locations[(search_round_count + offset) % len(locations)]
            company_type = company_types[(search_round_count + offset) % len(company_types)]
            detail = detail_signals[(search_round_count + offset) % len(detail_signals)]
            query = f'"{role}" {cohort_signal} {location} {company_type} {detail}'
            if query.casefold() not in previous:
                queries.append(query)
        # A later round changes the detail signal and remains role-led.
        if not queries and profile.target_roles:
            role = profile.target_roles[search_round_count % len(profile.target_roles)]
            location = locations[search_round_count % len(locations)]
            queries = [f'"{role}" {cohort_signal} {location} {detail_signals[(search_round_count + 1) % 3]}']
        limit = (limits or SearchPlanLimits()).max_queries
        queries = [q for q in queries if q.casefold() not in previous][:limit]
        return SearchPlan(
            target_roles=profile.target_roles,
            locations=profile.preferred_locations,
            company_types=profile.preferred_company_types,
            queries=queries,
            cohort_year=cohort.cohort_year if cohort else None,
            graduation_start=cohort.graduation_start if cohort else None,
            graduation_end=cohort.graduation_end if cohort else None,
            cohort_terms=cohort.search_terms if cohort else [],
        )

    def build_from_context(self, context: SearchStrategyContext) -> SearchPlan:
        return self.build(
            context.profile, context.search_round_count, context.previous_queries,
            context.previous_results, context.limits,
        )
