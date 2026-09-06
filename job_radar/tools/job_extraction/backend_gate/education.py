"""Deterministic education normalization for Basic Gate."""

import re


EDUCATION_RANK = {
    "high_school": 1,
    "associate": 2,
    "bachelor": 3,
    "master": 4,
    "doctorate": 5,
}


EDUCATION_ALIASES = {
    "high_school": (
        "高中",
        "高中学历",
        "中专",
        "中等专业学校",
        "职高",
        "职业高中",
        "中职",
        "中等职业学校",
        "技校",
        "技工学校",
        "high school",
        "high school diploma",
        "secondary school",
    ),
    "associate": (
        "专科",
        "专科学历",
        "大学专科",
        "大专",
        "大专学历",
        "associate degree",
        "associate's degree",
    ),
    "bachelor": (
        "本科",
        "本科学历",
        "大学本科",
        "本科生",
        "学士",
        "学士学位",
        "bachelor",
        "bachelor's degree",
        "bachelors degree",
        "undergraduate",
        "undergraduate degree",
    ),
    "master": (
        "硕士",
        "硕士学历",
        "硕士研究生",
        "硕士学位",
        "研究生",
        "研究生学历",
        "master",
        "master's degree",
        "masters degree",
        "postgraduate",
    ),
    "doctorate": (
        "博士",
        "博士学历",
        "博士研究生",
        "博士学位",
        "doctorate",
        "doctoral",
        "doctoral degree",
        "phd",
        "ph.d",
    ),
}


def normalize_education_level(value: str | None) -> str | None:
    """Return the explicit minimum education level, or ``None`` if unknown."""

    if not value:
        return None

    text = _normalize_text(value)
    matched_levels = [
        level
        for level, aliases in EDUCATION_ALIASES.items()
        if any(_contains_alias(text, alias) for alias in aliases)
    ]

    if not matched_levels:
        return None

    return min(matched_levels, key=EDUCATION_RANK.__getitem__)


def normalize_education_levels(values: list[str]) -> list[str]:
    """Normalize explicit minimum levels; unknown values fail open downstream."""

    result: list[str] = []
    for value in values:
        normalized = normalize_education_level(value)
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def _normalize_text(value: str) -> str:
    text = " ".join(str(value).split()).casefold()
    return re.sub(r"[._-]+", " ", text)


def _contains_alias(text: str, alias: str) -> bool:
    alias = _normalize_text(alias)

    # Chinese expressions can be matched directly.
    if re.search(r"[\u4e00-\u9fff]", alias):
        return alias in text

    # English expressions use word boundaries to reduce false positives.
    pattern = rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])"
    return re.search(pattern, text, flags=re.I) is not None