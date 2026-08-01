"""Simple deterministic deduplication."""

from dataclasses import dataclass, field

from job_radar.models.job import JobRecord


@dataclass
class DeduplicationResult:
    """Unique records and duplicate records removed from a batch."""

    unique_records: list[JobRecord] = field(default_factory=list)
    duplicate_records: list[JobRecord] = field(default_factory=list)


def deduplicate_records(records: list[JobRecord]) -> DeduplicationResult:
    """Remove records with the same deduplication key, preferring official sources."""

    by_key: dict[str, JobRecord] = {}
    duplicates: list[JobRecord] = []

    for record in records:
        existing = by_key.get(record.deduplication_key)
        if existing is None:
            by_key[record.deduplication_key] = record
            continue
        duplicates.append(record)
        if record.is_official and not existing.is_official:
            by_key[record.deduplication_key] = record

    return DeduplicationResult(
        unique_records=list(by_key.values()),
        duplicate_records=duplicates,
    )
