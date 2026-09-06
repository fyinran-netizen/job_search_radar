from job_radar.tools.job_extraction.models import RawJobRecord
from job_radar.tools.job_extraction.normalization import normalize_records
from job_radar.frontend.job_service import JobService
from job_radar.infra.storage.repository import JobRepository
from job_radar.infra.paths import DEFAULT_DB_PATH


def make_job(title: str = "Data Analyst"):
    raw = RawJobRecord(
        company_name="Example Bank",
        company_type="Bank",
        title=title,
        location="Shanghai",
        description="Data analytics role using Python and SQL.",
        requirements="Python; SQL",
        recruitment_type="Campus Recruitment",
        graduation_years=["2026"],
        published_at="2026-07-01",
        deadline="2026-09-30",
        apply_url="https://example.invalid/apply",
        source_url="https://example.invalid",
        source_name="Example Careers",
        is_official=True,
    )
    job = normalize_records([raw])[0]
    return job


def test_sqlite_initialization_and_save_query(temp_db_path) -> None:
    repository = JobRepository(temp_db_path)
    result = repository.upsert_job(make_job())

    jobs = repository.list_jobs()

    assert result.action == "inserted"
    assert repository.count_jobs() == 1
    assert jobs[0].company_name == "Example Bank"
    assert not hasattr(jobs[0], "match_score")


def test_duplicate_import_does_not_add_record(temp_db_path) -> None:
    repository = JobRepository(temp_db_path)
    first_result = repository.upsert_job(make_job())
    second_result = repository.upsert_job(make_job())

    assert first_result.action == "inserted"
    assert second_result.action == "updated"
    assert repository.count_jobs() == 1


def test_reimport_preserves_user_status_and_notes(temp_db_path) -> None:
    repository = JobRepository(temp_db_path)
    repository.upsert_job(make_job())
    job_id = repository.list_jobs()[0].id
    assert job_id is not None

    repository.update_status_and_notes(job_id, "已投递", "Submitted on company site")
    changed_job = make_job()
    changed_job.description = "Updated source description"
    repository.upsert_job(changed_job)

    saved = repository.list_jobs()[0]
    assert saved.description == "Updated source description"
    assert saved.status == "已投递"
    assert saved.notes == "Submitted on company site"


def test_status_and_notes_update(temp_db_path) -> None:
    repository = JobRepository(temp_db_path)
    repository.upsert_job(make_job())
    job_id = repository.list_jobs()[0].id
    assert job_id is not None

    repository.update_status_and_notes(job_id, "感兴趣", "Review tomorrow")

    saved = repository.list_jobs()[0]
    assert saved.status == "感兴趣"
    assert saved.notes == "Review tomorrow"


def test_repository_reinitializes_after_database_delete(temp_db_path) -> None:
    repository = JobRepository(temp_db_path)
    repository.upsert_job(make_job())
    assert repository.count_jobs() == 1

    temp_db_path.unlink()

    reinitialized = JobRepository(temp_db_path)
    assert reinitialized.count_jobs() == 0


def test_services_use_temporary_database_in_tests(temp_db_path) -> None:
    assert temp_db_path != DEFAULT_DB_PATH

    service = JobService(temp_db_path)

    assert temp_db_path.exists()
    assert service.list_jobs() == []


