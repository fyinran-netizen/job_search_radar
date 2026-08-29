"""Guardrails for bounded agent decisions."""

from job_radar.tools.web_search.models import CandidateSource


def select_candidate_sources(sources: list[CandidateSource], min_relevance_score: int) -> list[CandidateSource]:
    """Select sources that are official and relevant enough for collection."""

    return [
        source
        for source in sources
        if source.relevance_score >= min_relevance_score
    ]


