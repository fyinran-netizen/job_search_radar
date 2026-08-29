"""Deterministic gates that run before AI understanding and matching."""

import re
from datetime import date

from job_radar.infra.logging import get_logger
from job_radar.tools.match_analysis.models import BasicGateResult
from job_radar.tools.job_extraction.models import JobRecord
from job_radar.profile.models import UserProfile
from job_radar.profile.cohort import infer_graduation_cohort


logger = get_logger(__name__)


def evaluate_basic_gate(job: JobRecord, profile: UserProfile, today: date | None = None) -> BasicGateResult:
    """Evaluate explicit facts that code can decide before AI understanding."""

    current_date = today or date.today()
    result = BasicGateResult()
    logger.info(
        "basic_gate title=%s candidate_graduation=%s job_years=%s window=%s..%s deadline=%s",
        job.title,
        profile.graduation_date,
        job.graduation_years,
        job.graduation_start,
        job.graduation_end,
        job.deadline,
    )

    if job.deadline:
        try:
            deadline = date.fromisoformat(job.deadline)
        except ValueError:
            result.risk_flags.append(f"invalid_deadline_format: {job.deadline}")
        else:
            if deadline < current_date:
                return BasicGateResult(
                    decision="skip",
                    hard_reject=True,
                    recommendation_override="skip",
                    gate_reasons=["Application deadline has passed."],
                    missing_requirements=[f"Deadline {job.deadline} is before {current_date.isoformat()}."],
                    risk_flags=["expired_deadline"],
                )

    cohort = infer_graduation_cohort(profile.graduation_date)
    profile_year = str(cohort.cohort_year) if cohort else None
    profile_graduation_month = _parse_year_month(profile.graduation_date)
    graduation_window = _graduation_window(job.graduation_start, job.graduation_end)
    if profile_graduation_month and graduation_window:
        start, end = graduation_window
        if (start and profile_graduation_month < start) or (end and profile_graduation_month > end):
            return BasicGateResult(
                decision="skip",
                hard_reject=True,
                recommendation_override="skip",
                gate_reasons=["Graduation eligibility window does not match."],
                missing_requirements=[
                    "Candidate graduation date "
                    f"{profile.graduation_date} is outside required window "
                    f"{job.graduation_start or 'unbounded'} to {job.graduation_end or 'unbounded'}."
                ],
                risk_flags=["graduation_window_mismatch"],
            )

    job_years = {_year for _year in job.graduation_years if _is_four_digit_year(_year)}
    if profile_year and job_years and profile_year not in job_years:
        if _has_explicit_graduation_requirement(job.graduation_requirement):
            return BasicGateResult(
                decision="skip",
                hard_reject=True,
                recommendation_override="skip",
                gate_reasons=["Graduation year eligibility does not match."],
                missing_requirements=[
                    f"Candidate graduation year {profile_year} is not in required years: {', '.join(sorted(job_years))}."
                ],
                risk_flags=["graduation_year_mismatch"],
            )
        result.risk_flags.append(
            "ambiguous_graduation_year_mismatch: "
            f"candidate {profile_year}, extracted {', '.join(sorted(job_years))}"
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
        return BasicGateResult(
            decision="skip",
            hard_reject=True,
            recommendation_override="skip",
            gate_reasons=["Job location is explicitly excluded by the candidate profile."],
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


def _is_four_digit_year(value: str) -> bool:
    return bool(re.fullmatch(r"(?:19|20)\d{2}", str(value).strip()))


def _parse_year_month(value: str | None) -> tuple[int, int] | None:
    if not value:
        return None
    match = re.fullmatch(r"\s*((?:19|20)\d{2})(?:-(0[1-9]|1[0-2])(?:-\d{2})?)?\s*", value)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2) or "06")


def _graduation_window(
    start: str | None,
    end: str | None,
) -> tuple[tuple[int, int] | None, tuple[int, int] | None] | None:
    start_month = _parse_year_month(start)
    end_month = _parse_year_month(end)
    if not start_month and not end_month:
        return None
    return start_month, end_month


def _has_explicit_graduation_requirement(value: str | None) -> bool:
    if not value:
        return False

    normalized = value.casefold()

    return any(
        marker in normalized
        for marker in (
            "graduat",
            "degree completion",
            "expected completion",
            "cohort",

            # Chinese
            "毕业",
            "应届",
            "届毕业生",
            "毕业时间",
            "毕业年份",

            # Japanese
            "卒業",
        )
    )


def _split_locations(value: str | None) -> list[str]:
    if not value:
        return []

    return [
        part.strip()
        for part in re.split(r"[,;/|，；、]+", value)
        if part.strip()
    ]

def _normalize_location_part(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


