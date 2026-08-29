"""Company-level views derived from prepared job records."""

from typing import Any

from job_radar.tools.job_extraction.models import JobRecord


def group_jobs_by_company(records: list[JobRecord]) -> list[dict[str, Any]]:
    """Return a compact company-first view without changing job-level records."""

    grouped: dict[str, dict[str, Any]] = {}
    for record in records:
        key = record.normalized_company_name or record.company_name
        group = grouped.setdefault(
            key,
            {
                "company_name": record.company_name,
                "normalized_company_name": record.normalized_company_name,
                "company_type": record.company_type,
                "is_official": record.is_official,
                "source_names": [],
                "source_urls": [],
                "job_count": 0,
                "jobs": [],
            },
        )
        _append_unique(group["source_names"], record.source_name)
        _append_unique(group["source_urls"], record.source_url)
        group["is_official"] = bool(group["is_official"]) or record.is_official
        if group["company_type"] is None and record.company_type:
            group["company_type"] = record.company_type
        group["job_count"] = int(group["job_count"]) + 1
        group["jobs"].append(_job_summary(record))

    return sorted(
        grouped.values(),
        key=lambda item: (-int(item["job_count"]), str(item["company_name"]).casefold()),
    )


def _job_summary(record: JobRecord) -> dict[str, Any]:
    return {
        "title": record.title,
        "normalized_title": record.normalized_title,
        "location": record.location,
        "normalized_location": record.normalized_location,
        "description": record.description,
        "requirements": record.requirements,
        "recruitment_type": record.recruitment_type,
        "graduation_years": record.graduation_years,
        "published_at": record.published_at,
        "deadline": record.deadline,
        "apply_url": record.apply_url,
        "source_url": record.source_url,
        "source_name": record.source_name,
        "deduplication_key": record.deduplication_key,
        "match_score": record.match_score,
        "match_reasons": record.match_reasons,
        "missing_requirements": record.missing_requirements,
    }


def _append_unique(items: Any, value: str | None) -> None:
    if not value or not isinstance(items, list):
        return
    if value not in items:
        items.append(value)


