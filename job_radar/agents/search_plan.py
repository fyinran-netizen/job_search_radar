"""Deterministic search-plan generation."""

from job_radar.agents.models import SearchPlan
from job_radar.models.profile import UserProfile


class SearchPlanBuilder:
    """Build a basic search plan from structured profile fields."""

    def build(self, profile: UserProfile) -> SearchPlan:
        """Create search keywords and filters from a profile."""

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
            keywords=self._deduplicate_keywords(keywords),
        )

    @staticmethod
    def _deduplicate_keywords(keywords: list[str]) -> list[str]:
        seen: set[str] = set()
        deduplicated: list[str] = []
        for keyword in keywords:
            normalized = keyword.lower().strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduplicated.append(keyword)
        return deduplicated
