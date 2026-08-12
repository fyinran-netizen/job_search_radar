"""Deterministic match rules that take priority over semantic AI analysis."""

import re
from datetime import date

from job_radar.models.job import JobRecord
from job_radar.models.match import (
    DeterministicMatchResult,
    FinalMatchAssessment,
    Recommendation,
    SemanticMatchAssessment,
)
from job_radar.models.profile import UserProfile
from job_radar.profile.cohort import infer_graduation_cohort


def evaluate_deterministic_match(job: JobRecord, profile: UserProfile, today: date | None = None) -> DeterministicMatchResult:
    """Evaluate hard match rules that code can decide without semantic judgment."""

    current_date = today or date.today()
    result = DeterministicMatchResult()

    if job.deadline:
        try:
            deadline = date.fromisoformat(job.deadline)
        except ValueError:
            result.risk_flags.append(f"Invalid deadline format: {job.deadline}")
        else:
            if deadline < current_date:
                return DeterministicMatchResult(
                    should_call_ai=False,
                    hard_reject=True,
                    recommendation_override="skip",
                    match_reasons=["Application deadline has passed."],
                    missing_requirements=[f"Deadline {job.deadline} is before {current_date.isoformat()}."],
                    risk_flags=["expired_deadline"],
                )

    cohort = infer_graduation_cohort(profile.graduation_date)
    profile_year = str(cohort.cohort_year) if cohort else None
    job_years = {_year for _year in job.graduation_years if _is_four_digit_year(_year)}
    if profile_year and job_years and profile_year not in job_years:
        return DeterministicMatchResult(
            should_call_ai=False,
            hard_reject=True,
            recommendation_override="skip",
            match_reasons=["Graduation year eligibility does not match."],
            missing_requirements=[
                f"Candidate graduation year {profile_year} is not in required years: {', '.join(sorted(job_years))}."
            ],
            risk_flags=["graduation_year_mismatch"],
        )

    excluded_locations = [_normalize_location_part(value) for value in profile.excluded_locations if value.strip()]
    job_locations = [_normalize_location_part(value) for value in _split_locations(job.location)]
    matched_excluded_locations = sorted(
        {
            excluded
            for excluded in excluded_locations
            if excluded and any(excluded in location or location in excluded for location in job_locations)
        }
    )
    if matched_excluded_locations and job_locations and len(matched_excluded_locations) >= len(job_locations):
        return DeterministicMatchResult(
            should_call_ai=False,
            hard_reject=True,
            recommendation_override="skip",
            match_reasons=["Job location is explicitly excluded by the candidate profile."],
            missing_requirements=[f"Excluded location matched: {', '.join(matched_excluded_locations)}."],
            risk_flags=["excluded_location"],
        )
    if matched_excluded_locations:
        result.risk_flags.append(f"partially_excluded_location: {', '.join(matched_excluded_locations)}")
        result.score_cap = 80

    if not job.is_official:
        result.risk_flags.append("non_official_source")
        result.score_cap = min(result.score_cap or 100, 90)

    return result


def build_deterministic_final(job: JobRecord, deterministic: DeterministicMatchResult) -> FinalMatchAssessment:
    """Create a final result for jobs that bypass AI."""

    return FinalMatchAssessment(
        match_score=0 if deterministic.hard_reject else min(job.match_score, deterministic.score_cap or 100),
        role_fit="unclear",
        must_have_fit="no" if deterministic.hard_reject else "unclear",
        match_reasons=deterministic.match_reasons,
        missing_requirements=deterministic.missing_requirements,
        risk_flags=deterministic.risk_flags,
        job_summary=f"{job.company_name} - {job.title}",
        recommendation=deterministic.recommendation_override or "low_priority",
        confidence="high",
        analysis_source="deterministic",
        deterministic_reasons=deterministic.match_reasons,
    )


def merge_match_results(
    semantic: SemanticMatchAssessment,
    deterministic: DeterministicMatchResult,
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

    confidence = semantic.confidence
    if deterministic.risk_flags and confidence == "high":
        confidence = "medium"

    return FinalMatchAssessment(
        match_score=score,
        role_fit=semantic.role_fit,
        must_have_fit=semantic.must_have_fit,
        match_reasons=_unique([*deterministic.match_reasons, *semantic.match_reasons]),
        missing_requirements=_unique([*deterministic.missing_requirements, *semantic.missing_requirements]),
        risk_flags=_unique([*deterministic.risk_flags, *semantic.risk_flags]),
        job_summary=semantic.job_summary,
        recommendation=recommendation,
        confidence=confidence,
        analysis_source="ai_with_deterministic_overrides" if _has_overrides(deterministic) else "ai",
        deterministic_reasons=deterministic.match_reasons,
    )


def _has_overrides(deterministic: DeterministicMatchResult) -> bool:
    return bool(
        deterministic.score_cap is not None
        or deterministic.recommendation_override
        or deterministic.match_reasons
        or deterministic.missing_requirements
        or deterministic.risk_flags
    )


def _is_four_digit_year(value: str) -> bool:
    return bool(re.fullmatch(r"(?:19|20)\d{2}", str(value).strip()))


def _split_locations(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in re.split(r"[,;/|，、]+", value) if part.strip()]


def _normalize_location_part(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


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
