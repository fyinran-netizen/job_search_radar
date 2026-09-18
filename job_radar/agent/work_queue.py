"""Generic, deterministic acquisition work-queue helpers."""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel, Field

from job_radar.tools.web_search.models import CandidateSource
from job_radar.tools.web_search.source_selection import normalize_url


class QueueAdmissionResult(BaseModel):
    """Auditable result of admitting sources to the global queue."""

    input_count: int = 0
    enqueued_count: int = 0
    duplicate_count: int = 0
    skipped_count: int = 0
    queue_size_after_enqueue: int = 0
    enqueued_sources: list[CandidateSource] = Field(default_factory=list)


def enqueue_sources(
    queue: Iterable[CandidateSource],
    sources: Iterable[CandidateSource],
    *,
    handled_urls: Iterable[str] = (),
    known_urls: Iterable[str] = (),
) -> tuple[list[CandidateSource], QueueAdmissionResult]:
    """Append eligible sources in stable order, returning the new queue.

    ``handled_urls`` covers terminal or already-processed URLs. ``known_urls``
    covers discovery history and is useful when admitting a new search round.
    Neither collection is mutated.
    """

    result_sources = list(queue)
    queued = {normalize_url(source.url) for source in result_sources}
    handled = {normalize_url(url) for url in handled_urls}
    known = {normalize_url(url) for url in known_urls}
    admitted: list[CandidateSource] = []
    duplicate_count = 0
    skipped_count = 0
    inputs = list(sources)

    for original in inputs:
        url = normalize_url(original.url)
        if not url or url in handled or url in known:
            skipped_count += 1
            continue
        if url in queued:
            duplicate_count += 1
            continue
        source = original.model_copy(update={"url": url})
        result_sources.append(source)
        admitted.append(source)
        queued.add(url)

    return result_sources, QueueAdmissionResult(
        input_count=len(inputs),
        enqueued_count=len(admitted),
        duplicate_count=duplicate_count,
        skipped_count=skipped_count,
        queue_size_after_enqueue=len(result_sources),
        enqueued_sources=admitted,
    )


def take_source_batch(
    queue: Iterable[CandidateSource], batch_size: int
) -> tuple[list[CandidateSource], list[CandidateSource]]:
    """Take at most ``batch_size`` sources, preserving queue order."""

    sources = list(queue)
    size = max(0, batch_size)
    return sources[:size], sources[size:]
