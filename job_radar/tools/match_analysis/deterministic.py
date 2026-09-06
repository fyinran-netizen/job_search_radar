"""Compatibility wrappers for deterministic checks used by match analysis."""

from job_radar.tools.match_analysis.models import BasicGateResult
from job_radar.tools.job_extraction.models import JobRecord
from job_radar.tools.match_analysis.models import FinalMatchAssessment, Recommendation, SemanticMatchAssessment
from job_radar.profile.models import UserProfile
from job_radar.tools.match_analysis.basic_gate import evaluate_basic_gate


DeterministicMatchResult = BasicGateResult


def evaluate_deterministic_match(job: JobRecord, profile: UserProfile, today=None) -> BasicGateResult:
    """Compatibility alias for the renamed program basic gate."""

    return evaluate_basic_gate(job, profile, today=today)


def build_deterministic_final(job: JobRecord, deterministic: BasicGateResult) -> FinalMatchAssessment:
    """Create a final result for jobs that bypass AI."""

    return FinalMatchAssessment(
        match_score=0 if deterministic.hard_reject else 0,
        role_fit="unclear",
        must_have_fit="no" if deterministic.hard_reject else "unclear",
        match_reasons=deterministic.gate_reasons,
        missing_requirements=deterministic.missing_requirements,
        risk_flags=deterministic.risk_flags,
        job_summary=f"{job.company_name} - {job.title}",
        recommendation=deterministic.recommendation_override or "low_priority",
        confidence="high",
        analysis_source="deterministic",
        deterministic_reasons=deterministic.gate_reasons,
    )


def merge_match_results(
    semantic: SemanticMatchAssessment,
    deterministic: BasicGateResult,
) -> FinalMatchAssessment:
    """Apply deterministic caps and risk flags to an AI semantic assessment."""

    score = semantic.match_score
    if deterministic.score_cap is not None:
        score = min(score, deterministic.score_cap)

    recommendation = deterministic.recommendation_override or semantic.recommendation
    if deterministic.score_cap is not None:
        recommendation = _more_conservative_recommendation(
            recommendation,
            _recommendation_for_score_cap(deterministic.score_cap),
        )
    recommendation = _more_conservative_recommendation(
        recommendation,
        _recommendation_for_score_cap(score),
    )

    confidence = semantic.confidence
    if deterministic.risk_flags and confidence == "high":
        confidence = "medium"

    return FinalMatchAssessment(
        match_score=score,
        role_fit=semantic.role_fit,
        must_have_fit=semantic.must_have_fit,
        match_reasons=_unique([*deterministic.gate_reasons, *semantic.match_reasons]),
        missing_requirements=_unique([*deterministic.missing_requirements, *semantic.missing_requirements]),
        risk_flags=_unique([*deterministic.risk_flags, *semantic.risk_flags]),
        job_summary=semantic.job_summary,
        recommendation=recommendation,
        confidence=confidence,
        analysis_source="ai_with_deterministic_overrides" if _has_overrides(deterministic) else "ai",
        deterministic_reasons=deterministic.gate_reasons,
    )


def _has_overrides(deterministic: BasicGateResult) -> bool:
    return bool(
        deterministic.score_cap is not None
        or deterministic.recommendation_override
        or deterministic.gate_reasons
        or deterministic.missing_requirements
        or deterministic.risk_flags
    )


def _unique(values: list[str]) -> list[str]:
    unique_values: list[str] = []
    for value in values:
        if value and value not in unique_values:
            unique_values.append(value)
    return unique_values


def _recommendation_for_score_cap(score_cap: int) -> Recommendation:
    if score_cap <= 39:
        return "skip"
    if score_cap <= 59:
        return "low_priority"
    if score_cap <= 79:
        return "consider"
    return "apply"


def _more_conservative_recommendation(left: Recommendation, right: Recommendation) -> Recommendation:
    severity = {
        "apply": 0,
        "consider": 1,
        "low_priority": 2,
        "skip": 3,
    }
    return left if severity[left] >= severity[right] else right


