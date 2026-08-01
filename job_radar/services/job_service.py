"""Job query and update use cases."""

from pathlib import Path

import pandas as pd

from job_radar.models.job import APPLICATION_STATUSES, JobRecord
from job_radar.storage.repository import JobRepository
from job_radar.utils.paths import DEFAULT_DB_PATH


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
                    "公司": job.company_name,
                    "公司类型": job.company_type,
                    "岗位": job.title,
                    "地点": job.location,
                    "匹配度": job.match_score,
                    "匹配原因": "；".join(job.match_reasons),
                    "缺失要求": "；".join(job.missing_requirements),
                    "状态": job.status,
                    "备注": job.notes,
                    "投递链接": job.apply_url or job.source_url,
                    "来源": job.source_name,
                }
            )
        return pd.DataFrame(rows)

    def update_status_and_notes(self, job_id: int, status: str, notes: str) -> None:
        """Persist user-managed status and notes."""

        if status not in APPLICATION_STATUSES:
            raise ValueError(f"Unsupported application status: {status}")
        self.repository.update_status_and_notes(job_id, status, notes)
