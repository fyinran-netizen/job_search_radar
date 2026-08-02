"""End-to-end pipeline orchestration."""

from dataclasses import asdict, dataclass, field
from collections.abc import Callable
from typing import Any

from job_radar.models.job import RawJobRecord
from job_radar.models.profile import MatchingRules, UserProfile
from job_radar.pipeline.deduplication import deduplicate_records
from job_radar.pipeline.matching import match_records
from job_radar.pipeline.normalization import normalize_records
from job_radar.pipeline.validation import ValidationErrorItem, validate_records
from job_radar.storage.repository import JobRepository
from job_radar.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class PipelineResult:
    """Summary from a pipeline run."""

    collected_count: int = 0
    valid_count: int = 0
    invalid_count: int = 0
    duplicate_count: int = 0
    inserted_count: int = 0
    updated_count: int = 0
    failed_count: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)


class PipelineRunner:
    """Coordinate collection, processing, matching, and persistence."""

    def __init__(
        self,
        collect_raw_records: Callable[[], list[RawJobRecord]],
        repository: JobRepository,
        profile: UserProfile,
        rules: MatchingRules,
    ) -> None:
        self.collect_raw_records = collect_raw_records
        self.repository = repository
        self.profile = profile
        self.rules = rules

    def run(self) -> PipelineResult:
        """Run the complete ingestion pipeline."""

        result = PipelineResult()
        raw_records = self.collect_raw_records()
        result.collected_count = len(raw_records)

        validation_result = validate_records(raw_records)
        result.valid_count = len(validation_result.valid_records)
        result.invalid_count = len(validation_result.errors)
        result.errors = [asdict(error) for error in validation_result.errors]

        normalized = normalize_records(validation_result.valid_records)
        deduplicated = deduplicate_records(normalized)
        result.duplicate_count = len(deduplicated.duplicate_records)

        matched = match_records(deduplicated.unique_records, self.profile, self.rules)
        persistence_result = self.repository.upsert_jobs(matched)
        result.inserted_count = persistence_result.inserted_count
        result.updated_count = persistence_result.updated_count
        result.failed_count = persistence_result.failed_count
        result.errors.extend(persistence_result.errors)

        for error in validation_result.errors:
            self._log_validation_error(error)
        return result

    @staticmethod
    def _log_validation_error(error: ValidationErrorItem) -> None:
        logger.warning("Invalid job record %s: %s", error.index, error.reason)
