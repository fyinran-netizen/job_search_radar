"""Single interpretation and consumption layer for agent work."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel, Field

from job_radar.agent.action_names import AgentActionName
from job_radar.agent.models import AgentLimits, AgentState
from job_radar.tools.explore_followups.common import normalized_http_url, normalized_url_set
from job_radar.tools.web_search.models import CandidateSource
from job_radar.tools.web_search.url_utils import normalize_url


BATCHED_ACTIONS: tuple[AgentActionName, ...] = (
    "acquire_page",
    "analyze_page",
    "job_extraction",
    "explore_followups",
    "job_understanding",
    "match_analysis",
)


class QueueAdmissionResult(BaseModel):
    """Auditable result of one source-admission operation."""

    input_count: int = 0
    enqueued_count: int = 0
    duplicate_count: int = 0
    handled_count: int = 0
    invalid_count: int = 0
    limited_count: int = 0
    skipped_count: int = 0
    queue_size_after_enqueue: int = 0
    enqueued_sources: list[CandidateSource] = Field(default_factory=list)


def enqueue_sources(
    queue: Iterable[CandidateSource],
    sources: Iterable[CandidateSource],
    *,
    handled_urls: Iterable[str] = (),
    max_sources: int | None = None,
) -> tuple[list[CandidateSource], QueueAdmissionResult]:
    """Normalize, deduplicate, bound, and append sources in stable order."""

    result_queue = list(queue)
    queued = {normalize_url(source.url) for source in result_queue}
    handled = {normalize_url(url) for url in handled_urls}
    inputs = list(sources)
    admitted: list[CandidateSource] = []
    duplicate_count = handled_count = invalid_count = limited_count = 0

    for original in inputs:
        if not original.url or not original.url.strip():
            invalid_count += 1
            continue
        try:
            url = normalize_url(original.url)
        except ValueError:
            invalid_count += 1
            continue
        if not url:
            invalid_count += 1
            continue
        if url in handled:
            handled_count += 1
            continue
        if url in queued:
            duplicate_count += 1
            continue
        if max_sources is not None and len(admitted) >= max_sources:
            limited_count += 1
            continue
        source = original.model_copy(update={"url": url})
        result_queue.append(source)
        admitted.append(source)
        queued.add(url)

    skipped_count = duplicate_count + handled_count + invalid_count + limited_count
    return result_queue, QueueAdmissionResult(
        input_count=len(inputs),
        enqueued_count=len(admitted),
        duplicate_count=duplicate_count,
        handled_count=handled_count,
        invalid_count=invalid_count,
        limited_count=limited_count,
        skipped_count=skipped_count,
        queue_size_after_enqueue=len(result_queue),
        enqueued_sources=admitted,
    )


def get_pending_work(state: AgentState, action: AgentActionName) -> list[Any]:
    """Derive an action backlog from artifacts and completion markers."""

    if action == "acquire_page":
        return list(state.acquisition_queue)
    if action == "analyze_page":
        completed = set(state.analyzed_page_urls)
        return [page for page in state.acquired_pages if page.url not in completed]
    if action == "job_extraction":
        completed = set(state.extracted_page_urls)
        return [page for page in state.job_detail_pages if page.url not in completed]
    if action == "explore_followups":
        return list(state.pending_followups)
    if action == "job_understanding":
        completed = set(state.understood_job_keys)
        return [job for job in state.prepared_jobs if job.deduplication_key not in completed]
    if action == "match_analysis":
        completed = set(state.matched_job_keys)
        return [record for record in state.understanding_records if record.deduplication_key not in completed]
    return []


def get_pending_count(state: AgentState, action: AgentActionName) -> int:
    return len(get_pending_work(state, action))


def is_followup_executable(state: AgentState, item: Any) -> bool:
    """Return whether a followup has at least one genuinely executable href."""

    if item.pending_kind != "navigation_required":
        return False
    excluded = get_followup_excluded_urls(state)
    explored = normalized_url_set(state.explored_followup_links)
    return any(
        (url := normalized_http_url(link.get("href") or link.get("url")))
        and url not in excluded
        and url not in explored
        for link in item.links
    )


def get_executable_count(state: AgentState, action: AgentActionName) -> int:
    if action != "explore_followups":
        return get_pending_count(state, action)
    return sum(is_followup_executable(state, item) for item in get_pending_work(state, action))


def get_action_batch_size(limits: AgentLimits, action: AgentActionName) -> int | None:
    return {
        "acquire_page": limits.acquire_batch_size,
        "analyze_page": limits.analyze_batch_size,
        "job_extraction": limits.extraction_batch_size,
        "explore_followups": limits.followup_batch_size,
        "job_understanding": limits.understanding_batch_size,
        "match_analysis": limits.match_batch_size,
    }.get(action)


def take_action_batch(
    state: AgentState, action: AgentActionName, batch_size: int
) -> tuple[list[Any], list[Any]]:
    """Take a bounded batch and return the remaining derived backlog."""

    pending = get_pending_work(state, action)
    if action != "explore_followups":
        size = max(0, batch_size)
        return pending[:size], pending[size:]

    selected: list[Any] = []
    selected_indexes: set[int] = set()
    for index, item in enumerate(pending):
        if len(selected) >= batch_size or not is_followup_executable(state, item):
            continue
        selected.append(item)
        selected_indexes.add(index)
    remaining = [item for index, item in enumerate(pending) if index not in selected_indexes]
    return selected, remaining


def get_followup_excluded_urls(state: AgentState) -> set[str]:
    urls = {normalize_url(page.url) for page in state.acquired_pages}
    urls.update(normalize_url(source.url) for source in state.acquisition_queue)
    urls.update(normalize_url(item.url) for item in state.rejected_pages)
    urls.update(normalize_url(error.url) for error in state.errors if error.url)
    return urls
