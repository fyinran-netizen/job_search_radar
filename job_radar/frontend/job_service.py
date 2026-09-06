"""Job query and update use cases."""

from pathlib import Path

import pandas as pd

from job_radar.tools.job_extraction.models import APPLICATION_STATUSES, JobRecord
from job_radar.infra.storage.repository import JobRepository
from job_radar.infra.paths import DEFAULT_DB_PATH


class JobService:
    """Application service for persisted job records."""

    def __init__(self, db_path: Path = DEFAULT_DB_PATH) -> None:
        self.repository = JobRepository(db_path)

    def list_jobs(self) -> list[JobRecord]:
        """Return all stored jobs."""

        return self.repository.list_jobs()

    def jobs_dataframe(self) -> pd.DataFrame:
        """Return jobs as a display-friendly dataframe."""

        rows = []
        for job in self.list_jobs():
            rows.append(
                {
                    "id": job.id,
                    "company": job.company_name,
                    "company type": job.company_type,
                    "title": job.title,
                    "location": job.location,
                    "status": job.status,
                    "notes": job.notes,
                    "source url": job.source_url,
                    "source": job.source_name,
                }
            )

        return pd.DataFrame(rows)

    def update_status_and_notes(self, job_id: int, status: str, notes: str) -> None:
        """Persist user-managed status and notes."""

        if status not in APPLICATION_STATUSES:
            raise ValueError(f"Unsupported application status: {status}")
        self.repository.update_status_and_notes(job_id, status, notes)


