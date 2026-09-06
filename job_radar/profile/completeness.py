"""Deterministic profile completeness validation."""

import re
from collections.abc import Callable
from dataclasses import dataclass

from job_radar.profile.models import ProfileCompletenessResult, UserProfile


@dataclass(frozen=True)
class RequiredProfileField:
    """One required profile field and its validation rule."""

    name: str
    question: str
    is_present: Callable[[UserProfile], bool]


def _has_non_empty_items(values: list[str]) -> bool:
    return any(item.strip() for item in values)


def _has_graduation_year(profile: UserProfile) -> bool:
    """Accept either a year or year-month value such as 2026 or 2026-06."""

    return bool(re.search(r"\b(?:19|20)\d{2}\b", profile.graduation_date.strip()))


DEFAULT_REQUIRED_FIELDS = [
    RequiredProfileField(
        name="target_roles",
        question="Add at least one target role.",
        is_present=lambda profile: _has_non_empty_items(profile.target_roles),
    ),
    RequiredProfileField(
        name="skills",
        question="Add at least one skill keyword.",
        is_present=lambda profile: _has_non_empty_items(profile.skills),
    ),
    RequiredProfileField(
        name="graduation_date",
        question="Add expected graduation year or date, for example 2026 or 2026-06.",
        is_present=_has_graduation_year,
    ),
    RequiredProfileField(
        name="preferred_locations",
        question="Add at least one preferred location.",
        is_present=lambda profile: _has_non_empty_items(profile.preferred_locations),
    ),
]


class ProfileCompletenessChecker:
    """Rule-based checker that decides whether search can start."""

    def __init__(self, required_fields: list[RequiredProfileField] | None = None) -> None:
        self.required_fields = required_fields or DEFAULT_REQUIRED_FIELDS

    def check(self, profile: UserProfile) -> ProfileCompletenessResult:
        """Return missing required fields and direct follow-up questions."""

        missing = []
        questions = []
        for field in self.required_fields:
            if not field.is_present(profile):
                missing.append(field.name)
                questions.append(field.question)
        return ProfileCompletenessResult(
            is_complete=not missing,
            missing_fields=missing,
            questions=questions,
        )


