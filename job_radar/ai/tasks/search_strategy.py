"""Build search strategy objects from a user profile."""

from job_radar.models.profile import UserProfile
from job_radar.models.search import SearchPlan


class SearchPlanBuilder:
    """Deterministic fallback for future AI-backed search strategy generation."""

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
