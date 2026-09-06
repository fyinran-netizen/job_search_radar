import pytest
from pydantic import ValidationError

from job_radar.tools.job_extraction.models import JobRecord, RawJobRecord
from job_radar.tools.job_extraction.normalization import normalize_records


def test_raw_job_record_parses_graduation_years() -> None:
    record = RawJobRecord(
        company_name="Example",
        title="Data Analyst",
        locations=["Shanghai"],
        source_name="Demo",
        graduation_years="2026; 2027",
        is_official=True,
    )

    assert record.graduation_years == ["2026", "2027"]


def test_job_record_requires_deduplication_key() -> None:
    with pytest.raises(ValidationError):
        JobRecord(company_name="Example", title="Data Analyst", locations=["Shanghai"], source_name="Demo")


def test_normalization_creates_processed_job_record() -> None:
    raw = RawJobRecord(
        company_name=" Example  Bank ",
        company_type="Bank",
        title=" Data Analyst ",
        locations=["Shanghai", "Remote"],
        source_name="Demo",
        apply_url="https://example.invalid/apply",
    )

    job = normalize_records([raw])[0]

    assert job.company_name == "Example Bank"
    assert job.title == "Data Analyst"
    assert job.locations == ["Shanghai", "Remote"]
    assert job.deduplication_key == "url|https example invalid apply"


