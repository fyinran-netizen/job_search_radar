"""Normalize validated raw job records into persistable records."""

import re

from job_radar.models.job import JobRecord, RawJobRecord


def normalize_text(value: str | None) -> str:
    """Collapse whitespace and strip punctuation that affects matching."""

    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def normalize_key_part(value: str | None) -> str:
    """Normalize a string for deduplication keys."""

    text = normalize_text(value).lower()
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_location(value: str | None) -> str:
    """Normalize common location separators for display."""

    text = normalize_text(value)
    text = re.sub(r"\s*(?:、|，|,|；|;|/|\\|\|)\s*", ", ", text)
    return re.sub(r"\s*,\s*", ", ", text).strip(" ,")


def normalize_graduation_years(values: list[str]) -> list[str]:
    """Return unique four-digit graduation years in stable numeric order."""

    years = {
        match.group(0)
        for value in values
        for match in re.finditer(r"(?<!\d)(?:19|20)\d{2}(?!\d)", str(value))
    }
    return sorted(years)


def build_deduplication_key(company_name: str, title: str, location: str | None) -> str:
    """Create a deterministic deduplication key."""

    return "|".join(
        [
            normalize_key_part(company_name),
            normalize_key_part(title),
            normalize_key_part(location),
        ]
    )


def normalize_records(records: list[RawJobRecord]) -> list[JobRecord]:
    """Convert raw records to normalized job records."""

    normalized: list[JobRecord] = []
    for record in records:
        company_name = normalize_text(record.company_name)
        title = normalize_text(record.title)
        location = normalize_location(record.location) or None
        data = record.model_dump()
        data.update(
            {
                "company_name": company_name,
                "company_type": normalize_text(record.company_type) or None,
                "title": title,
                "location": location,
                "description": normalize_text(record.description) or None,
                "requirements": normalize_text(record.requirements) or None,
                "recruitment_type": normalize_text(record.recruitment_type) or None,
                "graduation_years": normalize_graduation_years(record.graduation_years),
                "source_name": normalize_text(record.source_name),
                "normalized_company_name": normalize_key_part(company_name),
                "normalized_title": normalize_key_part(title),
                "normalized_location": normalize_key_part(location),
                "deduplication_key": build_deduplication_key(company_name, title, location),
            }
        )
        normalized.append(
            JobRecord(**data)
        )
    return normalized
