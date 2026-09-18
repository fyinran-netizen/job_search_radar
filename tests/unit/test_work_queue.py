from job_radar.agent.models import AgentState
from job_radar.agent.work_queue import enqueue_sources, take_source_batch
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
    assert result.skipped_count == 0


def test_enqueue_skips_handled_urls() -> None:
    queue, result = enqueue_sources([], [source("https://example.test/a")], handled_urls=["https://example.test/a/"])

    assert queue == []
    assert result.skipped_count == 1


def test_take_source_batch_leaves_remaining_queue() -> None:
    batch, remaining = take_source_batch([source("https://example.test/1"), source("https://example.test/2")], 1)

    assert [item.url for item in batch] == ["https://example.test/1"]
    assert [item.url for item in remaining] == ["https://example.test/2"]


def test_checkpoint_round_trip_includes_acquisition_queue() -> None:
    state = AgentState(
        acquisition_queue=[source("https://example.test/a")],
        acquired_pages=[PageDocument(url="https://example.test/done", source_name="Example")],
    )

    assert AgentState.model_validate(state.model_dump(mode="json")) == state
