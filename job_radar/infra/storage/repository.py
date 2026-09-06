"""Repository methods for job persistence."""

from dataclasses import dataclass, field
import json
import sqlite3
from pathlib import Path
from typing import Any

from job_radar.tools.job_extraction.models import APPLICATION_STATUSES, JobRecord, utc_now_iso
from job_radar.infra.logging import get_logger
from job_radar.infra.storage.database import connection_scope, initialize_database


logger = get_logger(__name__)


@dataclass
class UpsertJobResult:
    """Persistence result for one job."""

    job_id: int | None
    action: str


@dataclass
class UpsertJobsResult:
    """Aggregate persistence result for a batch of jobs."""

    inserted_count: int = 0
    updated_count: int = 0
    failed_count: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)


class JobRepository:
    """SQLite repository for job records."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        initialize_database(db_path)

    def upsert_job(self, job: JobRecord) -> UpsertJobResult:
        """Insert or update a job while preserving user status and notes."""

        payload = self._to_row(job)
        with connection_scope(self.db_path) as connection:
            existing = connection.execute(
                "SELECT id FROM jobs WHERE deduplication_key = ?",
                (job.deduplication_key,),
            ).fetchone()

            if existing is None:
                cursor = connection.execute(
                    """
                    INSERT INTO jobs (
                        company_name, company_type, title, location, description, requirements,
                        recruitment_type, graduation_years, published_at, deadline, apply_url,
                        source_url, source_name, is_official, normalized_company_name,
                        normalized_title, normalized_location, deduplication_key, match_score,
                        match_reasons, missing_requirements, status, notes, first_seen_at,
                        last_seen_at, created_at, updated_at
                    )
                    VALUES (
                        :company_name, :company_type, :title, :location, :description, :requirements,
                        :recruitment_type, :graduation_years, :published_at, :deadline, :apply_url,
                        :source_url, :source_name, :is_official, :normalized_company_name,
                        :normalized_title, :normalized_location, :deduplication_key, :match_score,
                        :match_reasons, :missing_requirements, :status, :notes, :first_seen_at,
                        :last_seen_at, :created_at, :updated_at
                    )
                    """,
                    payload,
                )
                return UpsertJobResult(job_id=int(cursor.lastrowid), action="inserted")

            connection.execute(
                """
                UPDATE jobs
                SET company_name = :company_name,
                    company_type = :company_type,
                    title = :title,
                    location = :location,
                    description = :description,
                    requirements = :requirements,
                    recruitment_type = :recruitment_type,
                    graduation_years = :graduation_years,
                    published_at = :published_at,
                    deadline = :deadline,
                    apply_url = :apply_url,
                    source_url = :source_url,
                    source_name = :source_name,
                    is_official = :is_official,
                    normalized_company_name = :normalized_company_name,
                    normalized_title = :normalized_title,
                    normalized_location = :normalized_location,
                    match_score = :match_score,
                    match_reasons = :match_reasons,
                    missing_requirements = :missing_requirements,
                    last_seen_at = :last_seen_at,
                    updated_at = :updated_at
                WHERE deduplication_key = :deduplication_key
                """,
                payload,
            )
            return UpsertJobResult(job_id=int(existing["id"]), action="updated")

    def upsert_jobs(self, jobs: list[JobRecord]) -> UpsertJobsResult:
        """Save jobs and report inserted, updated, and failed counts."""

        result = UpsertJobsResult()
        for job in jobs:
            try:
                item = self.upsert_job(job)
            except Exception as exc:
                result.failed_count += 1
                result.errors.append(
                    {
                        "stage": "persistence",
                        "deduplication_key": job.deduplication_key,
                        "company_name": job.company_name,
                        "title": job.title,
                        "reason": str(exc),
                    }
                )
                continue

            if item.action == "inserted":
                result.inserted_count += 1
            elif item.action == "updated":
                result.updated_count += 1
        logger.info(
            "persistence saved=%s inserted=%s updated=%s failed=%s",
            len(jobs) - result.failed_count,
            result.inserted_count,
            result.updated_count,
            result.failed_count,
        )
        return result

    def list_jobs(self) -> list[JobRecord]:
        """Return all jobs ordered by score and first seen time."""

        with connection_scope(self.db_path) as connection:
            rows = connection.execute(
                "SELECT * FROM jobs ORDER BY match_score DESC, first_seen_at DESC, id DESC"
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def update_status_and_notes(self, job_id: int, status: str, notes: str) -> None:
        """Update user-managed status and notes for one job."""

        if status not in APPLICATION_STATUSES:
            raise ValueError(f"Unsupported application status: {status}")
        with connection_scope(self.db_path) as connection:
            connection.execute(
                """
                UPDATE jobs
                SET status = ?, notes = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, notes, utc_now_iso(), job_id),
            )

    def count_jobs(self) -> int:
        """Return the number of persisted jobs."""

        with connection_scope(self.db_path) as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM jobs").fetchone()
        return int(row["count"])

    @staticmethod
    def _to_row(job: JobRecord) -> dict[str, Any]:
        data = job.model_dump()
        data["graduation_years"] = json.dumps(job.graduation_years, ensure_ascii=False)
        # Legacy columns remain in the existing jobs table, but match output is
        # no longer part of the prepared JobRecord contract.
        data["match_score"] = 0
        data["match_reasons"] = "[]"
        data["missing_requirements"] = "[]"
        data["is_official"] = 1 if job.is_official else 0
        return data

    @staticmethod
    def _from_row(row: sqlite3.Row) -> JobRecord:
        data = dict(row)
        data["graduation_years"] = json.loads(data["graduation_years"])
        data.pop("match_score", None)
        data.pop("match_reasons", None)
        data.pop("missing_requirements", None)
        data["is_official"] = bool(data["is_official"])
        return JobRecord.model_validate(data)


