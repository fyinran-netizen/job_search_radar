"""Mixed strategy for page-analysis routing outcomes."""

import json

from job_radar.agent.models import AgentState
from job_radar.infra.llm.base import AIProvider
from job_radar.agent.controllers.llm_controller.outcome_summary.common import (
    call_summary_llm,
    deterministic_summary,
    fields,
    new_items,
)


def summarize(before: AgentState, after: AgentState, provider: AIProvider | None, timeout_seconds: int) -> str:
    new_job_detail_pages = new_items(before.job_detail_pages, after.job_detail_pages, "url")
    new_followups = new_items(before.pending_followups, after.pending_followups, "url")
    new_rejections = new_items(before.rejected_pages, after.rejected_pages, "url")
    deterministic = (
        "Page analysis routed "
        f"{len(new_job_detail_pages)} new job-detail page(s), "
        f"{len(new_followups)} follow-up(s), and "
        f"{len(new_rejections)} rejection(s)."
    )
    projection = {
        "job_detail_pages": fields(new_job_detail_pages, ("title", "source_name", "is_official")),
        "followups": fields(new_followups, ("title", "pending_kind", "reasons", "suggested_next_action", "priority")),
        "rejections": fields(new_rejections, ("title", "reasons")),
    }
    if not any(projection.values()):
        return deterministic_summary(deterministic + " No new routing evidence is available for semantic interpretation.")
    prompt = "\n".join([
        "Summarize the workflow meaning of these page-analysis routing results.",
        "Describe the presence and role of job-detail pages for the next extraction step.",
        "Explain what follow-up paths are mainly indicated and the main reasons for rejection.",
        "Discuss coverage, quality, or insufficiency only when supported by the supplied evidence.",
        "Do not infer page content that is not present in the projection.",
        json.dumps(projection, ensure_ascii=False),
        '{"summary": "short semantic outcome"}',
    ])
    semantic = call_summary_llm(provider, prompt, timeout_seconds)
    return deterministic_summary(deterministic + " " + (semantic or "Routing evidence was classified for extraction, follow-up, or rejection."))


__all__ = ["summarize"]
