"""Guardrails for bounded agent decisions."""

from job_radar.models.search import CandidateSource


def select_candidate_sources(sources: list[CandidateSource], min_relevance_score: int) -> list[CandidateSource]:
    """Select sources that are official and relevant enough for collection."""

    return [
        source
        for source in sources
        if source.is_official and source.relevance_score >= min_relevance_score
    ]
