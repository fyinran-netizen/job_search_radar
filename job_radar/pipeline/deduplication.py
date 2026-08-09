"""Simple deterministic deduplication."""

from dataclasses import dataclass, field

from job_radar.models.job import JobRecord


@dataclass
class DeduplicationResult:
    """Unique records and duplicate records removed from a batch."""

    unique_records: list[JobRecord] = field(default_factory=list)
    duplicate_records: list[JobRecord] = field(default_factory=list)


def _record_quality(record: JobRecord) -> tuple[int, int]:
    """Rank equivalent records by provenance and useful field coverage."""

    populated_fields = sum(
        bool(getattr(record, field_name))
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
    return int(record.is_official), populated_fields


def deduplicate_records(records: list[JobRecord]) -> DeduplicationResult:
    """Remove records with the same deduplication key, preferring official sources."""

    by_key: dict[str, JobRecord] = {}
    duplicates: list[JobRecord] = []

    for record in records:
        existing = by_key.get(record.deduplication_key)
        if existing is None:
            by_key[record.deduplication_key] = record
            continue
        if _record_quality(record) > _record_quality(existing):
            by_key[record.deduplication_key] = record
            duplicates.append(existing)
        else:
            duplicates.append(record)

    return DeduplicationResult(
        unique_records=list(by_key.values()),
        duplicate_records=duplicates,
    )
