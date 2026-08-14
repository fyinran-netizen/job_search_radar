"""Structured job understanding models."""

from typing import Literal

from pydantic import BaseModel, Field

from job_radar.models.gate import BasicGateResult
from job_radar.models.job import JobRecord

RequirementImportance = Literal["hard", "preferred", "context", "unclear"]
RequirementCategory = Literal[
    "education",
    "major_or_discipline",
    "credential_or_license",
    "technical_skill",
    "domain_knowledge",
    "communication",
    "language",
    "experience",
    "portfolio_or_work_sample",
    "availability",
    "location",
    "work_authorization",
    "graduation_or_cohort",
    "personal_attribute",
    "other",
]
Seniority = Literal["internship", "graduate", "entry_level", "experienced", "leadership", "unclear"]
Confidence = Literal["high", "medium", "low"]
UnderstandingSource = Literal["ai", "skipped_by_basic_gate"]


class RequirementFact(BaseModel):
    """One requirement or preference extracted from the job text."""

    category: RequirementCategory
    importance: RequirementImportance
    text: str
    evidence: str | None = None


class JobRequirementFacts(BaseModel):
    """Structured, discipline-neutral facts extracted from one prepared job."""

    canonical_role: str
    role_family: str | None = None
    seniority: Seniority = "unclear"
    responsibilities: list[str] = Field(default_factory=list)
    hard_requirements: list[RequirementFact] = Field(default_factory=list)
    preferred_requirements: list[RequirementFact] = Field(default_factory=list)
    eligibility_constraints: list[RequirementFact] = Field(default_factory=list)
    work_context: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    confidence: Confidence


class JobUnderstandingRecord(BaseModel):
    """Understanding artifact for one prepared job."""

    deduplication_key: str
    company_name: str
    title: str
    job: JobRecord
    basic_gate: BasicGateResult
    understanding: JobRequirementFacts | None = None
    source: UnderstandingSource


class JobUnderstandingInput(BaseModel):
    """Stable payload passed to AI understanding providers."""

    prepared_job: JobRecord
    candidate_profile_context: dict[str, object] = Field(default_factory=dict)
