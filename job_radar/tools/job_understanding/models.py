"""Structured job understanding models."""

from typing import Literal

from pydantic import BaseModel, Field

from job_radar.tools.job_extraction.models import BasicGateResult


RequirementCategory = Literal[
    "major_or_discipline",
    "credential_or_license",
    "technical_skill",
    "domain_knowledge",
    "communication",
    "language",
    "experience",
    "portfolio_or_work_sample",
    "availability",
    "personal_attribute",
    "other",
]

Seniority = Literal[
    "internship",
    "graduate",
    "entry_level",
    "experienced",
    "leadership",
    "unclear",
]

Confidence = Literal["high", "medium", "low"]
UnderstandingSource = Literal["ai"]


class RequirementFact(BaseModel):
    """One semantic candidate requirement extracted from the job text."""

    category: RequirementCategory
    text: str
    evidence: str | None = None


class JobRequirementFacts(BaseModel):
    """Structured semantic understanding of one prepared job."""

    canonical_role: str
    role_family: str | None = None
    seniority: Seniority = "unclear"
    responsibilities: list[str] = Field(default_factory=list)
    requirements: list[RequirementFact] = Field(default_factory=list)
    work_context: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    confidence: Confidence


class JobUnderstandingRecord(BaseModel):
    """Understanding artifact for one prepared job."""

    deduplication_key: str
    basic_gate: BasicGateResult
    understanding: JobRequirementFacts | None = None
    source: UnderstandingSource


class JobUnderstandingInput(BaseModel):
    """Stable job-only payload passed to AI understanding providers."""

    title: str | None = None
    description: str | None = None
    requirements: str | None = None
    recruitment_type: str | None = None