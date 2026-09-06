"""Graduation cohort helpers used by search and deterministic matching."""

import re

from pydantic import BaseModel


class GraduationCohort(BaseModel):
    """Normalized campus recruitment cohort window."""

    cohort_year: int
    graduation_start: str
    graduation_end: str
    cohort_label: str
    search_terms: list[str]

    @property
    def label(self) -> str:
        return self.cohort_label

    @property
    def graduation_window(self) -> tuple[str, str]:
        return self.graduation_start, self.graduation_end


def infer_graduation_cohort(graduation_date: str) -> GraduationCohort | None:
    """Infer cohort from a year or year-month value.

    A 2027 cohort means expected graduation between 2026-09 and 2027-06.
    If a concrete month is September or later, it belongs to the next cohort.
    """

    text = graduation_date.strip()
    if not text:
        return None
    year_month = re.search(r"(?<!\d)((?:19|20)\d{2})[-/.](0?[1-9]|1[0-2])(?!\d)", text)
    if year_month:
        year = int(year_month.group(1))
        month = int(year_month.group(2))
        cohort_year = year + 1 if month >= 9 else year
        return _build_cohort(cohort_year)

    year_match = re.search(r"(?<!\d)((?:19|20)\d{2})(?!\d)", text)
    if year_match:
        return _build_cohort(int(year_match.group(1)))
    return None


def _build_cohort(cohort_year: int) -> GraduationCohort:
    previous_year = cohort_year - 1

    return GraduationCohort(
        cohort_year=cohort_year,
        graduation_start=f"{previous_year}-09",
        graduation_end=f"{cohort_year}-06",
        cohort_label=f"{cohort_year}届",
        search_terms=[
            f"{cohort_year}届",
            f"{cohort_year}校招",
            f"{cohort_year}校园招聘",
            f"{cohort_year} graduate",
            f"{cohort_year} Graduate Program",
        ],
    )


