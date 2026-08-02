"""Determine whether a profile has enough information to search."""

from job_radar.models.decisions import ProfileCompletenessResult
from job_radar.models.profile import UserProfile


DEFAULT_REQUIRED_FIELDS = {
    "target_roles": "Add at least one target role.",
    "skills": "Add at least one skill keyword.",
    "graduation_date": "Add expected graduation date.",
}


class ProfileCompletenessChecker:
    """Deterministic fallback for profile completeness decisions."""

    def __init__(self, required_fields: dict[str, str] | None = None) -> None:
        self.required_fields = required_fields or DEFAULT_REQUIRED_FIELDS

    def check(self, profile: UserProfile) -> ProfileCompletenessResult:
        """Return missing fields and user-facing questions."""

        missing = []
        questions = []
        for field_name, question in self.required_fields.items():
            value = getattr(profile, field_name)
            if not value:
                missing.append(field_name)
                questions.append(question)
        return ProfileCompletenessResult(
            is_complete=not missing,
            missing_fields=missing,
            questions=questions,
        )
