"""Validated user-profile boundary models."""

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


def _clean_text(value: Any) -> str:
    """Normalize a form/config text value without inventing content."""

    if value is None:
        return ""
    return " ".join(str(value).split())


def _clean_items(value: Any) -> list[str]:
    """Normalize, split, filter, and stably deduplicate profile list values."""

    if value is None:
        return []
    if isinstance(value, str):
        values: Sequence[Any] = value.replace(",", "\n").replace(";", "\n").splitlines()
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        values = value
    else:
        values = [value]

    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        cleaned = _clean_text(item)
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


class UserProfile(BaseModel):
    """Structured, cleaned candidate profile shared by all downstream stages."""

    education: str = ""
    graduation_date: str = ""
    target_roles: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    preferred_company_types: list[str] = Field(default_factory=list)
    preferred_locations: list[str] = Field(default_factory=list)
    excluded_locations: list[str] = Field(default_factory=list)

    @field_validator("education", "graduation_date", mode="before")
    @classmethod
    def normalize_text_fields(cls, value: Any) -> str:
        return _clean_text(value)

    @field_validator(
        "target_roles",
        "skills",
        "preferred_company_types",
        "preferred_locations",
        "excluded_locations",
        mode="before",
    )
    @classmethod
    def normalize_list_fields(cls, value: Any) -> list[str]:
        return _clean_items(value)

    @model_validator(mode="after")
    def validate_location_preferences(self) -> "UserProfile":
        preferred = {item.casefold() for item in self.preferred_locations}
        excluded = {item.casefold() for item in self.excluded_locations}
        conflicts = sorted(preferred & excluded)
        if conflicts:
            raise ValueError(
                "preferred_locations and excluded_locations cannot overlap: "
                + ", ".join(conflicts)
            )
        return self

    @classmethod
    def from_form_data(cls, data: Mapping[str, Any]) -> "UserProfile":
        """Create a profile from Streamlit form data at the input boundary."""

        return cls.model_validate(dict(data))


class ProfileCompletenessResult(BaseModel):
    """Result of deterministic profile completeness validation."""

    is_complete: bool
    missing_fields: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)




