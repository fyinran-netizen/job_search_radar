"""Deterministic aggregation for match analysis."""

from typing import Iterable

from job_radar.profile.models import UserProfile
from job_radar.tools.job_extraction.backend_gate.location import normalize_locations
from job_radar.tools.job_extraction.models import BasicGateResult, JobRecord
from job_radar.tools.job_understanding.models import JobRequirementFacts
from job_radar.tools.match_analysis.models import (
    FinalMatchAssessment,
    Recommendation,
    ScoringRubric,
    SemanticMatchAssessment,
)


def build_final_assessment(
    job: JobRecord,
    understanding: JobRequirementFacts | None,
    semantic: SemanticMatchAssessment | None,
    profile: UserProfile,
    gate: BasicGateResult,
    rubric: ScoringRubric | None = None,
) -> FinalMatchAssessment:
    """Combine stored gate facts and semantic evidence into the final result."""

    if gate.hard_reject or semantic is None:
        return FinalMatchAssessment(
            match_score=0,
            role_fit="unclear",
            must_have_fit="no" if gate.hard_reject else "unclear",
            match_reasons=_unique(gate.gate_reasons),
            missing_requirements=_unique(gate.missing_requirements),
            risk_flags=_risk_flags(job, gate.risk_flags),
            confidence="high",
            analysis_source="deterministic_only",
            deterministic_reasons=list(gate.gate_reasons),
            score_components={"eligibility": 0},
            recommendation=gate.recommendation_override or "skip",
        )

    rubric = rubric or ScoringRubric()
    components = score_components(job, semantic, profile, gate)
    total_weight = sum(rubric.model_dump().values())
    weighted = sum(
        components[name] * weight
        for name, weight in rubric.model_dump().items()
    ) // total_weight
    score = max(0, min(100, weighted))
    if gate.score_cap is not None:
        score = min(score, gate.score_cap)
    recommendation = gate.recommendation_override or recommendation_for_score(score)
    confidence = _final_confidence(semantic.confidence, understanding, gate)
    semantic_data = semantic.model_dump()
    semantic_data.update(
        match_reasons=_unique([*gate.gate_reasons, *semantic.match_reasons]),
        missing_requirements=_unique([*gate.missing_requirements, *semantic.missing_requirements]),
        risk_flags=_risk_flags(job, [*gate.risk_flags, *semantic.risk_flags]),
        confidence=confidence,
    )
    return FinalMatchAssessment(
        **semantic_data,
        match_score=score,
        recommendation=recommendation,
        # The score and recommendation are always program-owned, so every
        # semantic result has passed through deterministic aggregation.
        analysis_source="semantic_with_program_scoring",
        deterministic_reasons=list(gate.gate_reasons),
        score_components=components,
    )


def score_components(
    job: JobRecord,
    semantic: SemanticMatchAssessment,
    profile: UserProfile,
    gate: BasicGateResult,
) -> dict[str, int]:
    """Return 0-100 component scores using normalized, structured inputs."""

    role = {"high": 100, "medium": 65, "low": 20, "unclear": 40}[semantic.role_fit]
    requirements = {"yes": 100, "partial": 60, "no": 20, "unclear": 40}[semantic.must_have_fit]
    eligibility = 0 if gate.hard_reject else max(0, 100 - 10 * len(gate.risk_flags))
    location = _location_score(job, profile)
    return {
        "role_alignment": role,
        "requirement_fit": requirements,
        "eligibility": eligibility,
        "location_preference": location,
    }


def recommendation_for_score(score: int) -> Recommendation:
    if score >= 70:
        return "apply"
    if score >= 40:
        return "consider"
    if score >= 20:
        return "low_priority"
    return "skip"


def _location_score(job: JobRecord, profile: UserProfile) -> int:
    preferred = normalize_locations(profile.preferred_locations)
    # Job locations are already canonicalized by extraction/normalization.
    locations = job.locations
    if not preferred or not locations:
        return 50
    preferred_values = set(preferred)
    return 100 if any(value in preferred_values for value in locations) else 50


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _risk_flags(job: JobRecord, values: Iterable[str]) -> list[str]:
    flags = list(values)
    if not job.is_official:
        flags.append("non_official_source")
    return _unique(flags)


def _final_confidence(
    semantic_confidence: str,
    understanding: JobRequirementFacts | None,
    gate: BasicGateResult,
) -> str:
    confidence_rank = {"low": 0, "medium": 1, "high": 2}
    confidence = semantic_confidence
    if understanding is not None and confidence_rank[understanding.confidence] < confidence_rank[confidence]:
        confidence = understanding.confidence
    if gate.risk_flags and confidence == "high":
        confidence = "medium"
    return confidence
