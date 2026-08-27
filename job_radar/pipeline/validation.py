"""Validation for raw job records."""

from dataclasses import dataclass, field
from datetime import date
from urllib.parse import urlparse

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


ALLOWED_URL_SCHEMES = {"http", "https", "file", "mock"}


def _is_safe_absolute_url(value: str) -> bool:
    parsed = urlparse(value)
    if parsed.scheme not in ALLOWED_URL_SCHEMES:
        return False
    if parsed.scheme == "file":
        return bool(parsed.path)
    return bool(parsed.netloc)


def _is_iso_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def validate_records(records: list[RawJobRecord]) -> ValidationResult:
    """Validate required raw job fields without failing the full batch."""

    result = ValidationResult()
    for index, record in enumerate(records, start=1):
        missing = [
            field_name
            for field_name in REQUIRED_FIELDS
            if not getattr(record, field_name) or not str(getattr(record, field_name)).strip()
        ]
        if not record.source_url:
            missing.append("source_url")

        invalid: list[str] = []
        for field_name in ("source_url", "apply_url"):
            value = getattr(record, field_name)
            if value and not _is_safe_absolute_url(value):
                invalid.append(f"{field_name} must be a supported absolute URL")
        for field_name in ("published_at", "deadline"):
            value = getattr(record, field_name)
            if value and not _is_iso_date(value):
                invalid.append(f"{field_name} must be an ISO 8601 date")
        if record.published_at and record.deadline:
            if _is_iso_date(record.published_at) and _is_iso_date(record.deadline):
                if date.fromisoformat(record.deadline) < date.fromisoformat(record.published_at):
                    invalid.append("deadline must not be earlier than published_at")

        if missing or invalid:
            reasons: list[str] = []
            if missing:
                reasons.append(f"Missing required field(s): {', '.join(missing)}")
            reasons.extend(invalid)
            result.errors.append(
                ValidationErrorItem(
                    index=index,
                    reason="; ".join(reasons),
                    company_name=record.company_name,
                    title=record.title,
                    source_name=record.source_name,
                )
            )
            continue
        result.valid_records.append(record)
    return result
