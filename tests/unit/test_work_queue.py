from job_radar.agent.work_manager import get_pending_count, get_pending_work, take_action_batch
from job_radar.agent.models import AgentLimits, AgentState
from job_radar.agent.work_manager import enqueue_sources
from job_radar.tools.page_acquisition.models import PageDocument
from job_radar.tools.web_search.models import CandidateSource


def source(url: str) -> CandidateSource:
    return CandidateSource(url=url, title=url, source_name="Example")


def test_enqueue_normalizes_deduplicates_and_preserves_order() -> None:
    queue, result = enqueue_sources(
        [source("https://example.test/a")],
        [source("https://example.test/a?utm_source=x"), source("https://example.test/b"), source("https://example.test/b")],
    )

    assert [item.url for item in queue] == ["https://example.test/a", "https://example.test/b"]
    assert result.input_count == 3
    assert result.enqueued_count == 1
    assert result.duplicate_count == 2
    assert result.skipped_count == 2


def test_enqueue_skips_handled_urls() -> None:
    queue, result = enqueue_sources([], [source("https://example.test/a")], handled_urls=["https://example.test/a/"])

    assert queue == []
    assert result.skipped_count == 1
    assert result.handled_count == 1


def test_admission_reports_each_skip_reason() -> None:
    queue, result = enqueue_sources(
        [source("https://example.test/duplicate")],
        [
            source("https://example.test/duplicate"),
            source("https://example.test/handled"),
            source(""),
            source("https://example.test/limited"),
        ],
        handled_urls=["https://example.test/handled"],
        max_sources=0,
    )

    assert queue == [source("https://example.test/duplicate")]
    assert result.duplicate_count == 1
    assert result.handled_count == 1
    assert result.invalid_count == 1
    assert result.limited_count == 1
    assert result.skipped_count == 4


def test_checkpoint_round_trip_includes_acquisition_queue() -> None:
    state = AgentState(
        acquisition_queue=[source("https://example.test/a")],
        acquired_pages=[PageDocument(url="https://example.test/done", source_name="Example")],
    )

    assert AgentState.model_validate(state.model_dump(mode="json")) == state


def test_action_backlog_is_derived_from_artifacts_and_completion_markers() -> None:
    state = AgentState(
        acquired_pages=[
            PageDocument(url="https://example.test/1", source_name="Example"),
            PageDocument(url="https://example.test/2", source_name="Example"),
        ],
        analyzed_page_urls=["https://example.test/1"],
    )

    assert get_pending_count(state, "analyze_page") == 1
    batch, remaining = take_action_batch(state, "analyze_page", AgentLimits().analyze_batch_size)
    assert [page.url for page in batch] == ["https://example.test/2"]
    assert remaining == []
    assert get_pending_work(state, "acquire_page") == []
