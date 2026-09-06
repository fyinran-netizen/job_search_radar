"""Normalize and deduplicate extracted job records."""

import re
from dataclasses import dataclass, field

from job_radar.tools.page_analysis.models import AIPageInput
from job_radar.tools.job_extraction.models import JobRecord, RawJobRecord


@dataclass
class DeduplicationResult:
    """Unique records and duplicates removed from a batch."""

    unique_records: list[
        JobRecord
    ] = field(default_factory=list)

    duplicate_records: list[
        JobRecord
    ] = field(default_factory=list)


def normalize_records(
    records: list[RawJobRecord],
) -> list[JobRecord]:
    """Convert raw records into normalized JobRecord objects."""

    normalized: list[
        JobRecord
    ] = []

    for record in records:
        company_name = normalize_text(
            record.company_name
        )

        title = normalize_text(
            record.title
        )

        location = (
            normalize_location(
                record.location
            )
            or None
        )

        data = record.model_dump()

        data.update(
            {
                "company_name": (
                    company_name
                ),
                "company_type": (
                    normalize_text(
                        record.company_type
                    )
                    or None
                ),
                "title": title,
                "location": location,
                "description": (
                    normalize_text(
                        record.description
                    )
                    or None
                ),
                "requirements": (
                    normalize_text(
                        record.requirements
                    )
                    or None
                ),
                "recruitment_type": (
                    normalize_text(
                        record.recruitment_type
                    )
                    or None
                ),
                "graduation_years": (
                    normalize_graduation_years(
                        record.graduation_years
                    )
                ),
                "graduation_start": (
                    normalize_text(
                        record.graduation_start
                    )
                    or None
                ),
                "graduation_end": (
                    normalize_text(
                        record.graduation_end
                    )
                    or None
                ),
                "graduation_requirement": (
                    normalize_text(
                        record.graduation_requirement
                    )
                    or None
                ),
                "start_date": (
                    normalize_text(
                        record.start_date
                    )
                    or None
                ),
                "start_date_text": (
                    normalize_text(
                        record.start_date_text
                    )
                    or None
                ),
                "source_name": (
                    normalize_text(
                        record.source_name
                    )
                ),
                "normalized_company_name": (
                    normalize_key_part(
                        company_name
                    )
                ),
                "normalized_title": (
                    normalize_key_part(
                        title
                    )
                ),
                "normalized_location": (
                    normalize_key_part(
                        location
                    )
                ),
                "deduplication_key": (
                    build_deduplication_key(
                        company_name,
                        title,
                        location,
                    )
                ),
            }
        )

        normalized.append(
            JobRecord(**data)
        )

    return normalized


def deduplicate_records(
    records: list[JobRecord],
) -> DeduplicationResult:
    """Remove duplicate jobs, preferring higher-quality records."""

    by_key: dict[
        str,
        JobRecord,
    ] = {}

    duplicates: list[
        JobRecord
    ] = []

    for record in records:
        existing = by_key.get(
            record.deduplication_key
        )

        if existing is None:
            by_key[
                record.deduplication_key
            ] = record

            continue

        if (
            _record_quality(record)
            > _record_quality(existing)
        ):
            by_key[
                record.deduplication_key
            ] = record

            duplicates.append(
                existing
            )

        else:
            duplicates.append(
                record
            )

    return DeduplicationResult(
        unique_records=list(
            by_key.values()
        ),
        duplicate_records=duplicates,
    )


def normalize_text(
    value: str | None,
) -> str:
    """Collapse whitespace."""

    if not value:
        return ""

    return re.sub(
        r"\s+",
        " ",
        value,
    ).strip()


def normalize_key_part(
    value: str | None,
) -> str:
    """Normalize a string for deterministic keys."""

    text = normalize_text(
        value
    ).lower()

    text = re.sub(
        r"[^a-z0-9\u4e00-\u9fff]+",
        " ",
        text,
    )

    return re.sub(
        r"\s+",
        " ",
        text,
    ).strip()


def normalize_location(
    value: str | None,
) -> str:
    """Normalize common Chinese and English location separators."""

    text = normalize_text(value)

    text = re.sub(
        r"\s*(?:、|，|；|,|;|/|\\|\|)\s*",
        ", ",
        text,
    )

    return re.sub(
        r"\s*,\s*",
        ", ",
        text,
    ).strip(" ,")


def normalize_graduation_years(
    values: list[str],
) -> list[str]:
    """Return unique four-digit graduation years."""

    years = {
        match.group(0)
        for value in values
        for match in re.finditer(
            r"(?<!\d)(?:19|20)\d{2}(?!\d)",
            str(value),
        )
    }

    return sorted(years)


def build_deduplication_key(
    company_name: str,
    title: str,
    location: str | None,
) -> str:
    """Create deterministic job identity key."""

    return "|".join(
        [
            normalize_key_part(
                company_name
            ),
            normalize_key_part(
                title
            ),
            normalize_key_part(
                location
            ),
        ]
    )


def _record_quality(
    record: JobRecord,
) -> tuple[int, int]:
    """Prefer official and more complete equivalent records."""

    populated_fields = sum(
        bool(
            getattr(
                record,
                field_name,
            )
        )
        for field_name in (
            "location",
            "description",
            "requirements",
            "recruitment_type",
            "graduation_years",
            "published_at",
            "deadline",
            "apply_url",
        )
    )

    return (
        int(record.is_official),
        populated_fields,
    )
