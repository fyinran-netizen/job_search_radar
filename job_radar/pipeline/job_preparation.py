"""Prepare extracted job records for later semantic analysis."""

from dataclasses import asdict, dataclass, field
from typing import Any

from job_radar.models.job import JobRecord, RawJobRecord
from job_radar.pipeline.deduplication import deduplicate_records
from job_radar.pipeline.normalization import normalize_records
from job_radar.pipeline.validation import validate_records


@dataclass
class JobPreparationResult:
    """Validated, normalized, and deduplicated jobs before matching."""

    raw_count: int = 0
    valid_count: int = 0
    invalid_count: int = 0
    duplicate_count: int = 0
    prepared_records: list[JobRecord] = field(default_factory=list)
    duplicate_records: list[JobRecord] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)


def prepare_records_for_analysis(records: list[RawJobRecord]) -> JobPreparationResult:
    """Validate, normalize, and deduplicate extracted raw records."""

    validation_result = validate_records(records)
    normalized = normalize_records(validation_result.valid_records)
    deduplicated = deduplicate_records(normalized)
    return JobPreparationResult(
        raw_count=len(records),
        valid_count=len(validation_result.valid_records),
        invalid_count=len(validation_result.errors),
        duplicate_count=len(deduplicated.duplicate_records),
        prepared_records=deduplicated.unique_records,
        duplicate_records=deduplicated.duplicate_records,
        errors=[asdict(error) for error in validation_result.errors],
    )
