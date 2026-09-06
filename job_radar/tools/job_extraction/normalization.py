"""Normalize and deduplicate extracted job records."""

import re
from datetime import date, datetime
from dataclasses import dataclass, field

from job_radar.tools.job_extraction.backend_gate.education import (
    normalize_education_level,
    normalize_education_levels,
)
from job_radar.tools.job_extraction.backend_gate.location import (
    normalize_location,
    normalize_locations,
)
from job_radar.tools.job_extraction.models import JobRecord, RawJobRecord


@dataclass
class DeduplicationResult:
    unique_records: list[JobRecord] = field(default_factory=list)
    duplicate_records: list[JobRecord] = field(default_factory=list)


def normalize_records(records: list[RawJobRecord]) -> list[JobRecord]:
    normalized: list[JobRecord] = []
    for record in records:
        company_name = normalize_text(record.company_name) or None
        title = normalize_text(record.title) or None
        locations = normalize_locations(record.locations)
        data = record.model_dump()
        data.update(company_name=company_name, title=title, locations=locations,
                    company_type=normalize_text(record.company_type) or None,
                    description=normalize_text(record.description) or None,
                    requirements=normalize_text(record.requirements) or None,
                    recruitment_type=normalize_text(record.recruitment_type) or None,
                    graduation_years=normalize_graduation_years(record.graduation_years),
                    graduation_start=normalize_date_text(record.graduation_start) or None,
                    graduation_end=normalize_date_text(record.graduation_end) or None,
                    graduation_requirement=normalize_text(record.graduation_requirement) or None,
                    deadline=normalize_date_text(record.deadline) or None,
                    education_levels=normalize_education_levels(record.education_levels),
                    source_name=normalize_text(record.source_name) or None,
                    deduplication_key=build_deduplication_key(
                        company_name or "", title or "", locations,
                        record.apply_url, record.source_url))
        normalized.append(JobRecord(**data))
    return normalized


def deduplicate_records(records: list[JobRecord]) -> DeduplicationResult:
    by_key: dict[str, JobRecord] = {}
    duplicates: list[JobRecord] = []
    for record in records:
        existing = by_key.get(record.deduplication_key)
        if existing is None:
            by_key[record.deduplication_key] = record
        elif _record_quality(record) > _record_quality(existing):
            by_key[record.deduplication_key] = record
            duplicates.append(existing)
        else:
            duplicates.append(record)
    return DeduplicationResult(list(by_key.values()), duplicates)


def normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value).strip() if value else ""


def normalize_key_part(value: str | None) -> str:
    text = normalize_text(value).casefold()
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_date_text(value: str | None) -> str:
    """Normalize supported date/date-time text to ISO strings, otherwise preserve it."""
    text = normalize_text(value)
    if not text:
        return ""
    candidate = text.replace("/", "-").replace(".", "-")
    for parser in (date.fromisoformat, datetime.fromisoformat):
        try:
            parsed = parser(candidate)
        except ValueError:
            continue
        return parsed.date().isoformat() if isinstance(parsed, datetime) else parsed.isoformat()
    match = re.fullmatch(r"((?:19|20)\d{2})-(0[1-9]|1[0-2])", candidate)
    return f"{match.group(1)}-{match.group(2)}" if match else text


def normalize_graduation_years(values: list[str]) -> list[str]:
    years = {match.group(0) for value in values
             for match in re.finditer(r"(?<!\d)(?:19|20)\d{2}(?!\d)", str(value))}
    return sorted(years)


def build_deduplication_key(company_name: str, title: str, locations: list[str],
                            apply_url: str | None = None, source_url: str | None = None) -> str:
    """Use stable URL identity first, then factual fields as a fallback."""
    for url in (apply_url, source_url):
        key = normalize_key_part(url)
        if key:
            return f"url|{key}"
    return "|".join(["fallback", normalize_key_part(company_name), normalize_key_part(title),
                     normalize_key_part(",".join(locations))])


def _record_quality(record: JobRecord) -> tuple[int, int]:
    populated_fields = sum(bool(getattr(record, name)) for name in (
        "locations", "description", "requirements", "recruitment_type", "graduation_years",
        "graduation_start", "graduation_end", "graduation_requirement", "education_levels",
        "deadline", "apply_url"))
    return int(record.is_official), populated_fields
