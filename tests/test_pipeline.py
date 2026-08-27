from job_radar.config import load_matching_rules, load_profile
from job_radar.models.job import RawJobRecord
from job_radar.pipeline.deduplication import deduplicate_records
from job_radar.pipeline.job_grouping import group_jobs_by_company
from job_radar.pipeline.job_preparation import prepare_records_for_analysis
from job_radar.pipeline.matching import match_records
from job_radar.pipeline.normalization import normalize_records
from job_radar.pipeline.runner import PipelineRunner
from job_radar.pipeline.validation import validate_records
from job_radar.storage.repository import JobRepository
from job_radar.utils.paths import CONFIG_DIR


def sample_raw_records() -> list[RawJobRecord]:
    return [
        RawJobRecord(
            company_name="China Mobile",
            company_type="State-owned Enterprise",
            title="Data Analyst Graduate",
            location="Shanghai",
            description="Analyze business data and build dashboards.",
            requirements="Python SQL data analysis",
            source_name="China Mobile Careers",
            source_url="https://careers.example/china-mobile/data-analyst",
            is_official=True,
        ),
        RawJobRecord(
            company_name="China Mobile",
            company_type="State-owned Enterprise",
            title="Data Analyst Graduate",
            location="Shanghai",
            description="Duplicate listing.",
            requirements="Python SQL",
            source_name="China Mobile Careers",
            source_url="https://careers.example/china-mobile/data-analyst-duplicate",
            is_official=True,
        ),
        RawJobRecord(
            company_name="Future Bank",
            company_type="Bank",
            title="Technology Graduate Analyst",
            location="Sydney",
            description="Build internal banking systems.",
            requirements="Python SQL stakeholder communication",
            source_name="Future Bank Careers",
            source_url="https://careers.example/future-bank/technology-graduate",
            is_official=True,
        ),
        RawJobRecord(
            company_name="Example Tech",
            company_type="Technology",
            title="Software Engineer Graduate",
            location="Shenzhen",
            description="Develop backend services.",
            requirements="Python distributed systems",
            source_name="Example Tech Careers",
            source_url="https://careers.example/example-tech/software-engineer",
        ),
        RawJobRecord(
            company_name="Consulting Co",
            company_type="Consulting",
            title="Business Analyst Graduate",
            location="Melbourne",
            description="Support client analysis.",
            requirements="SQL Excel stakeholder communication",
            source_name="Consulting Co Careers",
            source_url="https://careers.example/consulting/business-analyst",
        ),
        RawJobRecord(
            company_name="Broken Source",
            title=None,
            location="Beijing",
            source_name="Broken Careers",
            source_url="https://careers.example/broken",
        ),
    ]


def test_validation_rejects_invalid_job() -> None:
    records = sample_raw_records()
    result = validate_records(records)

    assert len(result.valid_records) == 5
    assert len(result.errors) == 1
    assert "title" in result.errors[0].reason


def test_validation_rejects_missing_location() -> None:
    record = RawJobRecord(
        company_name="Example",
        title="Graduate Analyst",
        location=None,
        source_name="Example Careers",
        source_url="https://careers.example/jobs/1",
    )

    validation = validate_records([record])

    assert validation.valid_records == []
    assert len(validation.errors) == 1
    assert "location" in validation.errors[0].reason


def test_validation_rejects_invalid_source_url_and_dates() -> None:
    record = RawJobRecord(
        company_name="Example",
        title="Graduate Analyst",
        source_name="Example Careers",
        source_url="not-a-url",
        published_at="01/08/2026",
    )

    result = validate_records([record])

    assert len(result.errors) == 1
    assert "source_url must be a supported absolute URL" in result.errors[0].reason
    assert "published_at must be an ISO 8601 date" in result.errors[0].reason


def test_normalization_canonicalizes_semantic_fields() -> None:
    record = RawJobRecord(
        company_name=" Example  Bank ",
        title="Graduate  Analyst",
        location="上海； 北京 / 深圳",
        description="Analyse\n  business data",
        requirements="Python\nSQL",
        graduation_years=["2027届", "2026", "2027"],
        source_name="Example Careers",
        source_url="https://careers.example/jobs/1",
    )

    normalized = normalize_records([record])[0]

    assert normalized.location == "上海, 北京, 深圳"
    assert normalized.description == "Analyse business data"
    assert normalized.requirements == "Python SQL"
    assert normalized.graduation_years == ["2026", "2027"]


def test_deduplication_removes_obvious_duplicate() -> None:
    records = sample_raw_records()
    valid = validate_records(records).valid_records
    normalized = normalize_records(valid)
    result = deduplicate_records(normalized)

    assert len(result.unique_records) == 4
    assert len(result.duplicate_records) == 1


def test_deduplication_keeps_richer_official_record() -> None:
    base = {
        "company_name": "Example Bank",
        "title": "Data Analyst",
        "location": "Shanghai",
        "source_name": "Example Careers",
    }
    third_party = RawJobRecord(
        **base,
        source_url="https://jobs.example/1",
        description="Summary",
    )
    official = RawJobRecord(
        **base,
        source_url="https://careers.example/1",
        description="Detailed description",
        requirements="Python and SQL",
        is_official=True,
    )

    result = deduplicate_records(normalize_records([third_party, official]))

    assert [record.source_url for record in result.unique_records] == ["https://careers.example/1"]
    assert [record.source_url for record in result.duplicate_records] == ["https://jobs.example/1"]


def test_prepare_records_for_analysis_stops_before_matching() -> None:
    records = sample_raw_records()

    result = prepare_records_for_analysis(records)

    assert result.raw_count == 6
    assert result.valid_count == 5
    assert result.invalid_count == 1
    assert result.duplicate_count == 1
    assert len(result.prepared_records) == 4
    assert result.prepared_records[0].deduplication_key
    assert result.prepared_records[0].match_score == 0
    assert result.errors


def test_group_jobs_by_company_returns_company_first_view() -> None:
    records = normalize_records(
        [
            RawJobRecord(
                company_name="Bank of China",
                company_type="Bank",
                title="Information Technology",
                location="Beijing",
                source_name="Bank of China",
                source_url="https://www.boc.cn/job/1",
                is_official=True,
            ),
            RawJobRecord(
                company_name="Bank of China",
                company_type="Bank",
                title="Data Analyst",
                location="Shanghai",
                source_name="Bank of China",
                source_url="https://www.boc.cn/job/2",
                is_official=True,
            ),
            RawJobRecord(
                company_name="Example Tech",
                company_type="Technology",
                title="Software Engineer",
                location="Sydney",
                source_name="Example Careers",
                source_url="https://careers.example/job/1",
            ),
        ]
    )

    grouped = group_jobs_by_company(records)

    assert [company["company_name"] for company in grouped] == ["Bank of China", "Example Tech"]
    assert grouped[0]["job_count"] == 2
    assert grouped[0]["source_names"] == ["Bank of China"]
    assert [job["title"] for job in grouped[0]["jobs"]] == ["Information Technology", "Data Analyst"]
    assert "company_name" not in grouped[0]["jobs"][0]


def test_matcher_outputs_score_and_reasons() -> None:
    profile, _, _ = load_profile(CONFIG_DIR)
    rules, _, _ = load_matching_rules(CONFIG_DIR)
    records = sample_raw_records()
    normalized = normalize_records(validate_records(records).valid_records)
    unique = deduplicate_records(normalized).unique_records

    matched = match_records(unique, profile, rules)

    assert matched[0].match_score > 0
    assert matched[0].match_reasons


def test_pipeline_result_counts(temp_db_path) -> None:
    profile, _, _ = load_profile(CONFIG_DIR)
    rules, _, _ = load_matching_rules(CONFIG_DIR)
    repository = JobRepository(temp_db_path)
    runner = PipelineRunner(sample_raw_records, repository, profile, rules)

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
