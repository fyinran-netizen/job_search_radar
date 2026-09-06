"""Persistence boundary for completed agent states."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from job_radar.agent.models import AgentState
from job_radar.infra.paths import DEFAULT_DB_PATH
from job_radar.infra.storage.repository import JobRepository, UpsertJobsResult
from job_radar.tools.job_extraction.models import JobRecord


@dataclass
class JobPersistenceService:
    """Merge match output and persist final jobs in the existing jobs DB."""

    db_path: Path = DEFAULT_DB_PATH

    def __post_init__(self) -> None:
        self.repository = JobRepository(self.db_path)

    def persist(self, state: AgentState) -> UpsertJobsResult:
        jobs = self.merge_match_results(state.prepared_jobs, state.match_assessments)
        return self.repository.upsert_jobs(jobs)

    @staticmethod
    def merge_match_results(jobs: list[JobRecord], assessments: list[dict[str, object]]) -> list[JobRecord]:
        """Return prepared facts unchanged; match results stay in their own artifact."""

        return list(jobs)


__all__ = ["JobPersistenceService"]
