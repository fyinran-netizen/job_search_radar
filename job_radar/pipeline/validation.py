"""Validation for raw job records."""

from dataclasses import dataclass, field

from job_radar.models.job import RawJobRecord


@dataclass
class ValidationErrorItem:
    """Validation error for one raw record."""

    index: int
    reason: str
    company_name: str | None = None
    title: str | None = None
    source_name: str | None = None


@dataclass
class ValidationResult:
    """Validated records and recoverable errors."""

    valid_records: list[RawJobRecord] = field(default_factory=list)
    errors: list[ValidationErrorItem] = field(default_factory=list)


REQUIRED_FIELDS = ["company_name", "title", "location", "source_name"]


def validate_records(records: list[RawJobRecord]) -> ValidationResult:
    """Validate required raw job fields without failing the full batch."""

    result = ValidationResult()
    for index, record in enumerate(records, start=1):
        missing = [
            field_name
            for field_name in REQUIRED_FIELDS
            if not getattr(record, field_name) or not str(getattr(record, field_name)).strip()
        ]
        if not record.apply_url and not record.source_url:
            missing.append("apply_url_or_source_url")
        if missing:
            result.errors.append(
                ValidationErrorItem(
                    index=index,
                    reason=f"Missing required field(s): {', '.join(missing)}",
                    company_name=record.company_name,
                    title=record.title,
                    source_name=record.source_name,
                )
            )
            continue
        result.valid_records.append(record)
    return result
