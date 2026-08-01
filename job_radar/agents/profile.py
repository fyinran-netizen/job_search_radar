"""Deterministic profile checks used before agent search."""

from job_radar.agents.models import ProfileCompletenessResult
from job_radar.models.profile import UserProfile


REQUIRED_PROFILE_FIELDS = {
    "target_roles": "Please provide at least one target role.",
    "preferred_locations": "Please provide at least one target location.",
    "graduation_date": "Please provide your graduation date or available start date.",
    "skills": "Please provide at least one core skill.",
}


class ProfileCompletenessChecker:
    """Check whether a profile contains the minimum fields needed for search."""

    def __init__(self, required_fields: dict[str, str] | None = None) -> None:
        self.required_fields = required_fields or REQUIRED_PROFILE_FIELDS

    def check(self, profile: UserProfile) -> ProfileCompletenessResult:
        """Return missing profile fields and clarification questions."""

        missing_fields: list[str] = []
        questions: list[str] = []
        for field_name, question in self.required_fields.items():
            value = getattr(profile, field_name)
            if not value:
                missing_fields.append(field_name)
                questions.append(question)
        return ProfileCompletenessResult(
            is_complete=not missing_fields,
            missing_fields=missing_fields,
            questions=questions,
        )
