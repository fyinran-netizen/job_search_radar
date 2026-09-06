"""Repository methods for factual job persistence and user-managed state."""

from dataclasses import dataclass, field
import json
import sqlite3
from pathlib import Path
from typing import Any

from job_radar.infra.logging import get_logger
from job_radar.infra.storage.database import connection_scope, initialize_database
from job_radar.tools.job_extraction.models import APPLICATION_STATUSES, JobRecord, utc_now_iso

logger = get_logger(__name__)


@dataclass
class UpsertJobResult:
    job_id: int | None
    action: str


@dataclass
class UpsertJobsResult:
    inserted_count: int = 0
    updated_count: int = 0
    failed_count: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)


class JobRepository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        initialize_database(db_path)

    def upsert_job(self, job: JobRecord) -> UpsertJobResult:
        payload = self._to_row(job)
        with connection_scope(self.db_path) as connection:
            existing = connection.execute("SELECT id FROM jobs WHERE deduplication_key = ?", (job.deduplication_key,)).fetchone()
            if existing is None:
                cursor = connection.execute("""
                    INSERT INTO jobs (company_name, company_type, title, locations, description, requirements,
                        recruitment_type, graduation_years, graduation_start, graduation_end, graduation_requirement,
                        deadline, education_levels, apply_url, source_url, source_name, is_official, deduplication_key,
                        status, notes, first_seen_at, last_seen_at, created_at, updated_at)
                    VALUES (:company_name, :company_type, :title, :locations, :description, :requirements,
                        :recruitment_type, :graduation_years, :graduation_start, :graduation_end, :graduation_requirement,
                        :deadline, :education_levels, :apply_url, :source_url, :source_name, :is_official, :deduplication_key,
                        :status, :notes, :first_seen_at, :last_seen_at, :created_at, :updated_at)
                """, payload)
                return UpsertJobResult(int(cursor.lastrowid), "inserted")
            connection.execute("""
                UPDATE jobs SET company_name=:company_name, company_type=:company_type, title=:title,
                    locations=:locations, description=:description, requirements=:requirements,
                    recruitment_type=:recruitment_type, graduation_years=:graduation_years,
                    graduation_start=:graduation_start, graduation_end=:graduation_end,
                    graduation_requirement=:graduation_requirement, deadline=:deadline,
                    education_levels=:education_levels, apply_url=:apply_url, source_url=:source_url,
                    source_name=:source_name, is_official=:is_official, last_seen_at=:last_seen_at,
                    updated_at=:updated_at WHERE deduplication_key=:deduplication_key
            """, payload)
            return UpsertJobResult(int(existing["id"]), "updated")

    def upsert_jobs(self, jobs: list[JobRecord]) -> UpsertJobsResult:
        result = UpsertJobsResult()
        for job in jobs:
            try:
                item = self.upsert_job(job)
            except Exception as exc:
                result.failed_count += 1
                result.errors.append({"stage": "persistence", "deduplication_key": job.deduplication_key,
                                      "company_name": job.company_name, "title": job.title, "reason": str(exc)})
                continue
            if item.action == "inserted": result.inserted_count += 1
            else: result.updated_count += 1
        logger.info("persistence inserted=%s updated=%s failed=%s", result.inserted_count, result.updated_count, result.failed_count)
        return result

    def list_jobs(self) -> list[JobRecord]:
        with connection_scope(self.db_path) as connection:
            rows = connection.execute("SELECT * FROM jobs ORDER BY first_seen_at DESC, id DESC").fetchall()
        return [self._from_row(row) for row in rows]

    def update_status_and_notes(self, job_id: int, status: str, notes: str) -> None:
        if status not in APPLICATION_STATUSES:
            raise ValueError(f"Unsupported application status: {status}")
        with connection_scope(self.db_path) as connection:
            connection.execute("UPDATE jobs SET status=?, notes=?, updated_at=? WHERE id=?", (status, notes, utc_now_iso(), job_id))

    def count_jobs(self) -> int:
        with connection_scope(self.db_path) as connection:
            return int(connection.execute("SELECT COUNT(*) AS count FROM jobs").fetchone()["count"])

    @staticmethod
    def _to_row(job: JobRecord) -> dict[str, Any]:
        data = job.model_dump()
        for name in ("locations", "graduation_years", "education_levels"):
            data[name] = json.dumps(data[name], ensure_ascii=False)
        data["is_official"] = int(job.is_official)
        return data

    @staticmethod
    def _from_row(row: sqlite3.Row) -> JobRecord:
        data = dict(row)
        for name in ("locations", "graduation_years", "education_levels"):
            data[name] = json.loads(data[name] or "[]")
        data["is_official"] = bool(data["is_official"])
        return JobRecord.model_validate(data)
