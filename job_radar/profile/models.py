"""User profile, completeness, and matching-rule models."""

from pydantic import BaseModel, Field


class UserProfile(BaseModel):
    """Non-private example profile used by the matcher."""

    education: str = ""
    graduation_date: str = ""
    target_roles: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    preferred_company_types: list[str] = Field(default_factory=list)
    preferred_locations: list[str] = Field(default_factory=list)
    excluded_locations: list[str] = Field(default_factory=list)


class ProfileCompletenessResult(BaseModel):
    """Result of deterministic profile completeness validation."""

    is_complete: bool
    missing_fields: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)


class MatchingRules(BaseModel):
    """Transparent rule configuration for scoring jobs."""

    title_keywords: list[str] = Field(default_factory=list)
    skill_keywords: list[str] = Field(default_factory=list)
    weights: dict[str, int] = Field(
        default_factory=lambda: {
            "title": 35,
            "skill": 30,
            "company_type": 15,
            "location": 20,
        }
    )


