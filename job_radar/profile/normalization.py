"""Candidate profile normalization helpers."""


def normalize_profile_text(value: str) -> str:
    """Collapse whitespace in a profile text field."""

    return " ".join(value.split())
