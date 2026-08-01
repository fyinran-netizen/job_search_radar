from job_radar.collectors.demo import DemoCollector
from job_radar.config import load_matching_rules, load_profile
from job_radar.pipeline.deduplication import deduplicate_records
from job_radar.pipeline.matching import match_records
from job_radar.pipeline.normalization import normalize_records
from job_radar.pipeline.runner import PipelineRunner
from job_radar.pipeline.validation import validate_records
from job_radar.storage.repository import JobRepository
from job_radar.utils.paths import CONFIG_DIR, DEMO_JOBS_PATH


def test_demo_collector_reads_demo_data() -> None:
    records = DemoCollector(DEMO_JOBS_PATH).collect()

    assert len(records) == 6
    assert records[0].company_name == "China Mobile"


def test_validation_rejects_invalid_job() -> None:
    records = DemoCollector(DEMO_JOBS_PATH).collect()
    result = validate_records(records)

    assert len(result.valid_records) == 5
    assert len(result.errors) == 1
    assert "title" in result.errors[0].reason


def test_deduplication_removes_obvious_duplicate() -> None:
    records = DemoCollector(DEMO_JOBS_PATH).collect()
    valid = validate_records(records).valid_records
    normalized = normalize_records(valid)
    result = deduplicate_records(normalized)

    assert len(result.unique_records) == 4
    assert len(result.duplicate_records) == 1


def test_matcher_outputs_score_and_reasons() -> None:
    profile, _, _ = load_profile(CONFIG_DIR)
    rules, _, _ = load_matching_rules(CONFIG_DIR)
    records = DemoCollector(DEMO_JOBS_PATH).collect()
    normalized = normalize_records(validate_records(records).valid_records)
    unique = deduplicate_records(normalized).unique_records

    matched = match_records(unique, profile, rules)

    assert matched[0].match_score > 0
    assert matched[0].match_reasons


def test_pipeline_result_counts(temp_db_path) -> None:
    profile, _, _ = load_profile(CONFIG_DIR)
    rules, _, _ = load_matching_rules(CONFIG_DIR)
    repository = JobRepository(temp_db_path)
    runner = PipelineRunner(DemoCollector(DEMO_JOBS_PATH), repository, profile, rules)

    result = runner.run()

    assert result.collected_count == 6
    assert result.valid_count == 5
    assert result.invalid_count == 1
    assert result.duplicate_count == 1
    assert result.inserted_count == 4
    assert result.updated_count == 0
    assert result.failed_count == 0
    assert repository.count_jobs() == 4

    second_result = runner.run()

    assert second_result.inserted_count == 0
    assert second_result.updated_count == 4
    assert second_result.failed_count == 0
    assert repository.count_jobs() == 4
