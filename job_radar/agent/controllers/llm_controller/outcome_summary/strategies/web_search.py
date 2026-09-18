"""Mixed strategy for web-search discovery outcomes."""

import json

from job_radar.agent.models import AgentState
from job_radar.infra.llm.base import AIProvider
from job_radar.tools.web_search.url_utils import normalize_url
from job_radar.agent.controllers.llm_controller.outcome_summary.common import (
    call_summary_llm,
    deterministic_summary,
    fields,
)


def summarize(
    before: AgentState,
    after: AgentState,
    provider: AIProvider | None,
    timeout_seconds: int,
) -> str:
    # The latest search-round result contains all sources returned in this round,
    # including sources that may already have been seen previously.
    round_sources = (
        after.search_round_results[-1]
        if len(after.search_round_results) > len(before.search_round_results)
        else []
    )

    previous_discovered_urls = {
        normalize_url(source.url)
        for source in before.candidate_sources
    }

    new_sources = [
        source
        for source in round_sources
        if normalize_url(source.url) not in previous_discovered_urls
    ]

    duplicate_count = len(round_sources) - len(new_sources)

    stats = {
        "returned_sources": len(round_sources),
        "new_sources": len(new_sources),
        "previously_seen_sources": duplicate_count,
        "selected_sources": len(after.selected_sources),
    }

    if not round_sources:
        return deterministic_summary(
            "Web search returned no candidate sources in this round."
        )

    source_projection = fields(
        new_sources,
        (
            "title",
            "source_name",
            "company_name",
            "company_type",
            "location",
            "is_official",
            "relevance_score",
            "reason",
        ),
    )

    selected_projection = fields(
        after.selected_sources,
        (
            "title",
            "source_name",
            "company_name",
            "location",
            "is_official",
            "relevance_score",
            "reason",
        ),
    )

    prompt = "\n".join([
        "Summarize the discovery value of this web-search round for the next controller decision.",
        "Use the supplied search statistics and source evidence to assess relevance, novelty, redundancy, source quality, and coverage.",
        "Explain whether the current search direction is still producing meaningfully new evidence or appears to be saturating.",
        "Do not infer job content or company characteristics that are not present in the supplied evidence.",
        f"Search statistics:\n{json.dumps(stats, ensure_ascii=False)}",
        f"New source evidence:\n{json.dumps(source_projection, ensure_ascii=False)}",
        f"Selected source evidence:\n{json.dumps(selected_projection, ensure_ascii=False)}",
        '{"summary": "short semantic outcome"}',
    ])

    semantic = call_summary_llm(
        provider,
        prompt,
        timeout_seconds,
    )

    if semantic:
        return semantic

    if new_sources:
        return deterministic_summary(
            f"Web search returned {len(round_sources)} source(s), "
            f"including {len(new_sources)} new source(s) and "
            f"{duplicate_count} previously seen source(s); "
            f"{len(after.selected_sources)} source(s) were selected."
        )

    return deterministic_summary(
        f"Web search returned {len(round_sources)} source(s), "
        "but all were previously seen and no new candidate-source evidence was added."
    )


__all__ = ["summarize"]
