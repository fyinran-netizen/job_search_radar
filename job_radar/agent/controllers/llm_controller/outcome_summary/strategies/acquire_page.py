"""Deterministic summary strategy for page acquisition."""

from job_radar.agent.models import AgentState
from job_radar.infra.llm.base import AIProvider
from job_radar.agent.controllers.llm_controller.outcome_summary.common import new_items


def summarize(
    before: AgentState,
    after: AgentState,
    provider: AIProvider | None,
    timeout_seconds: int,
) -> str:
    attempted_count = max(0, len(before.acquisition_queue) - len(after.acquisition_queue))

    new_pages = new_items(
        before.acquired_pages,
        after.acquired_pages,
        "url",
    )

    new_errors = after.errors[len(before.errors):]
    acquisition_failures = [
        error for error in new_errors
        if error.stage == "acquire_page"
    ]

    acquired_count = len(new_pages)
    failure_count = len(acquisition_failures)

    if attempted_count == 0:
        return "Page acquisition had no queued sources."

    if acquired_count == attempted_count:
        return (
            f"Page acquisition attempted {attempted_count} queued sources "
            f"and acquired all {acquired_count} pages successfully."
        )

    if acquired_count == 0:
        return (
            f"Page acquisition attempted {attempted_count} queued sources; "
            f"no pages were acquired and {failure_count} acquisition attempts failed."
        )

    return (
        f"Page acquisition attempted {attempted_count} queued sources: "
        f"{acquired_count} pages were acquired successfully and "
        f"{failure_count} acquisition attempts failed."
    )


__all__ = ["summarize"]
