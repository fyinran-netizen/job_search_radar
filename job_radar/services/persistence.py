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
        """Return final records without mutating checkpoint-owned model values."""

        by_key = {
            str(item.get("deduplication_key")): item.get("assessment")
            for item in assessments
            if item.get("deduplication_key") and isinstance(item.get("assessment"), dict)
        }
        final: list[JobRecord] = []
        for job in jobs:
            assessment = by_key.get(job.deduplication_key)
            if isinstance(assessment, dict):
                reasons = [str(item) for item in assessment.get("match_reasons", [])]
                if not reasons:
                    reasons = [f"Semantic match completed: recommendation={assessment.get('recommendation')}, confidence={assessment.get('confidence')}" ]
                job = job.model_copy(update={
                    "match_score": int(assessment.get("match_score", 0)),
                    "match_reasons": reasons,
                    "missing_requirements": [str(item) for item in assessment.get("missing_requirements", [])],
                })
            else:
                job = job.model_copy(update={
                    "match_score": 0,
                    "match_reasons": ["Semantic match was not completed for this job."],
                    "missing_requirements": [],
                })
            final.append(job)
        return final


__all__ = ["JobPersistenceService"]
