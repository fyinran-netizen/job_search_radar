from job_radar.config import load_matching_rules, load_profile
from job_radar.tools.job_extraction.models import RawJobRecord
from job_radar.tools.job_extraction.normalization import (
    deduplicate_records,
    normalize_education_levels,
    normalize_locations,
)
from job_radar.frontend.view_models import group_jobs_by_company
from job_radar.tools.match_analysis.rule_based import match_records
from job_radar.tools.job_extraction.normalization import normalize_records
from job_radar.tools.job_extraction.validation import validate_records
from job_radar.infra.storage.repository import JobRepository
from job_radar.infra.paths import CONFIG_DIR


def sample_raw_records() -> list[RawJobRecord]:
    return [
        RawJobRecord(
            company_name="China Mobile",
            company_type="State-owned Enterprise",
            title="Data Analyst Graduate",
            locations=["Shanghai"],
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
            locations=["Shanghai"],
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
            locations=["Sydney"],
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
            locations=["Shenzhen"],
            description="Develop backend services.",
            requirements="Python distributed systems",
            source_name="Example Tech Careers",
            source_url="https://careers.example/example-tech/software-engineer",
        ),
        RawJobRecord(
            company_name="Consulting Co",
            company_type="Consulting",
            title="Business Analyst Graduate",
            locations=["Melbourne"],
            description="Support client analysis.",
            requirements="SQL Excel stakeholder communication",
            source_name="Consulting Co Careers",
            source_url="https://careers.example/consulting/business-analyst",
        ),
        RawJobRecord(
            company_name="Broken Source",
            title=None,
            locations=["Beijing"],
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
        locations=[],
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
        deadline="01/08/2026",
    )

    result = validate_records([record])

    assert len(result.errors) == 1
    assert "source_url must be a supported absolute URL" in result.errors[0].reason
    assert "deadline must be an ISO 8601 date" in result.errors[0].reason


def test_normalization_canonicalizes_semantic_fields() -> None:
    record = RawJobRecord(
        company_name=" Example  Bank ",
        title="Graduate  Analyst",
        locations=["上海； 北京 / 深圳"],
        description="Analyse\n  business data",
        requirements="Python\nSQL",
        graduation_years=["2027届", "2026", "2027"],
        source_name="Example Careers",
        source_url="https://careers.example/jobs/1",
    )

    normalized = normalize_records([record])[0]

    assert normalized.locations == ["上海", "北京", "深圳"]
    assert normalized.description == "Analyse business data"
    assert normalized.requirements == "Python SQL"
    assert normalized.graduation_years == ["2026", "2027"]


def test_normalization_canonicalizes_education_locations_and_dates() -> None:
    assert normalize_education_levels(["本科", "本科及以上学历", "硕士及以上", "博士"]) == [
        "bachelor", "master", "doctorate"
    ]
    assert normalize_locations(["杭州（总部）", "Sydney (HQ)"]) == ["杭州", "Sydney"]
    job = normalize_records([RawJobRecord(
        company_name="Example",
        title="Role",
        locations=["Hangzhou"],
        graduation_start="2026/09",
        graduation_end="2027.06.30",
        deadline="2026/12/31",
        source_url="https://example.test/job",
    )])[0]
    assert job.graduation_start == "2026-09"
    assert job.graduation_end == "2027-06-30"
    assert job.deadline == "2026-12-31"


def test_deduplication_removes_obvious_duplicate() -> None:
    records = sample_raw_records()
    valid = validate_records(records).valid_records
    normalized = normalize_records(valid)
    result = deduplicate_records(normalized)

    assert len(result.unique_records) == 5
    assert len(result.duplicate_records) == 0


def test_deduplication_keeps_richer_official_record() -> None:
    base = {
        "company_name": "Example Bank",
        "title": "Data Analyst",
        "locations": ["Shanghai"],
        "source_name": "Example Careers",
    }
    third_party = RawJobRecord(
        **base,
        source_url=None,
        description="Summary",
    )
    official = RawJobRecord(
        **base,
        source_url=None,
        description="Detailed description",
        requirements="Python and SQL",
        is_official=True,
    )

    result = deduplicate_records(normalize_records([third_party, official]))

    assert [record.source_url for record in result.unique_records] == [None]
    assert [record.source_url for record in result.duplicate_records] == [None]


def test_group_jobs_by_company_returns_company_first_view() -> None:
    records = normalize_records(
        [
            RawJobRecord(
                company_name="Bank of China",
                company_type="Bank",
                title="Information Technology",
                locations=["Beijing"],
                source_name="Bank of China",
                source_url="https://www.boc.cn/job/1",
                is_official=True,
            ),
            RawJobRecord(
                company_name="Bank of China",
                company_type="Bank",
                title="Data Analyst",
                locations=["Shanghai"],
                source_name="Bank of China",
                source_url="https://www.boc.cn/job/2",
                is_official=True,
            ),
            RawJobRecord(
                company_name="Example Tech",
                company_type="Technology",
                title="Software Engineer",
                locations=["Sydney"],
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


