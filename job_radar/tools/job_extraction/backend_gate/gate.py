"""Basic Gate: explicit, deterministic hard eligibility checks only."""

import re
from datetime import date

from job_radar.infra.logging import get_logger
from job_radar.profile.cohort import infer_graduation_cohort
from job_radar.profile.models import UserProfile
from job_radar.tools.job_extraction.backend_gate.education import EDUCATION_RANK, normalize_education_level
from job_radar.tools.job_extraction.backend_gate.location import normalize_locations
from job_radar.tools.job_extraction.models import BasicGateResult, JobRecord


logger = get_logger(__name__)


def evaluate_basic_gate(job: JobRecord, profile: UserProfile, today: date | None = None) -> BasicGateResult:
    """Reject only when an explicit hard condition is deterministically false."""

    current_date = today or date.today()
    result = BasicGateResult()

    if job.deadline:
        try:
            deadline = date.fromisoformat(job.deadline)
        except ValueError:
            result.risk_flags.append(f"invalid_deadline_format: {job.deadline}")
        else:
            if deadline < current_date:
                return _reject(
                    "Application deadline has passed.",
                    f"Deadline {job.deadline} is before {current_date.isoformat()}.",
                    "expired_deadline",
                )
    else:
        result.risk_flags.append("deadline_unknown")

    cohort = infer_graduation_cohort(profile.graduation_date)
    profile_year = str(cohort.cohort_year) if cohort else None
    profile_month = _parse_year_month(profile.graduation_date)
    window = _graduation_window(job.graduation_start, job.graduation_end)
    has_graduation_data = bool(
        job.graduation_years
        or job.graduation_start
        or job.graduation_end
        or job.graduation_requirement
    )
    if not has_graduation_data:
        result.risk_flags.append("graduation_requirement_unknown")
    elif (
        (job.graduation_start or job.graduation_end or job.graduation_requirement)
        and window is None
        and not job.graduation_years
    ):
        result.risk_flags.append("graduation_requirement_unknown")
    if profile_month and window:
        start, end = window
        if (start and profile_month < start) or (end and profile_month > end):
            return _reject(
                "Graduation eligibility window does not match.",
                f"Candidate graduation date {profile.graduation_date} is outside required window.",
                "graduation_window_mismatch",
            )
    elif window and not profile_month:
        result.risk_flags.append("graduation_requirement_unknown")

    job_years = {year for year in job.graduation_years if _is_four_digit_year(year)}
    if job.graduation_years and not job_years:
        result.risk_flags.append("graduation_requirement_unknown")
    if profile_year and job_years and profile_year not in job_years:
        if _has_explicit_graduation_requirement(job.graduation_requirement):
            return _reject(
                "Graduation year eligibility does not match.",
                f"Candidate graduation year {profile_year} is not in required years: {', '.join(sorted(job_years))}.",
                "graduation_year_mismatch",
            )
        result.risk_flags.append(f"ambiguous_graduation_year_mismatch: candidate {profile_year}")
    elif job_years and not profile_year:
        result.risk_flags.append("graduation_requirement_unknown")

    required = {normalize_education_level(value) for value in job.education_levels}
    required.discard(None)
    candidate = normalize_education_level(profile.education)
    if not required:
        result.risk_flags.append("education_requirement_unknown")
    elif candidate not in EDUCATION_RANK:
        result.risk_flags.append("education_candidate_unknown")
    else:
        if not any(EDUCATION_RANK[candidate] >= EDUCATION_RANK[level] for level in required):
            return _reject(
                "Explicit education-level requirement does not match.",
                f"Required education level: {', '.join(sorted(required))}.",
                "education_level_mismatch",
            )

    excluded = normalize_locations(profile.excluded_locations)
    locations = normalize_locations(job.locations)
    if not locations:
        result.risk_flags.append("location_unknown")
    matches = sorted({item for item in excluded if any(_same_location(item, location) for location in locations)})
    if matches and locations and len(matches) == len(locations):
        return _reject(
            "Job location is explicitly excluded by the candidate profile.",
            f"Excluded location matched: {', '.join(matches)}.",
            "excluded_location",
        )
    return result


def _same_location(left: str, right: str) -> bool:
    return re.sub(r"\s+", "", left).casefold() == re.sub(r"\s+", "", right).casefold()


def _reject(reason: str, missing: str, flag: str) -> BasicGateResult:
    return BasicGateResult(
        decision="skip",
        hard_reject=True,
        recommendation_override="skip",
        gate_reasons=[reason],
        missing_requirements=[missing],
        risk_flags=[flag],
    )


def _is_four_digit_year(value: str) -> bool:
    return bool(re.fullmatch(r"(?:19|20)\d{2}", str(value).strip()))


def _parse_year_month(value: str | None) -> tuple[int, int] | None:
    if not value:
        return None
    match = re.fullmatch(r"\s*((?:19|20)\d{2})(?:-(0[1-9]|1[0-2])(?:-\d{2})?)?\s*", value)
    return (int(match.group(1)), int(match.group(2) or "06")) if match else None


def _graduation_window(start: str | None, end: str | None) -> tuple[tuple[int, int] | None, tuple[int, int] | None] | None:
    parsed = (_parse_year_month(start), _parse_year_month(end))
    return parsed if any(parsed) else None


def _has_explicit_graduation_requirement(value: str | None) -> bool:
    if not value:
        return False
    return any(marker in value.casefold() for marker in ("graduat", "degree completion", "expected completion", "cohort", "毕业", "应届"))
