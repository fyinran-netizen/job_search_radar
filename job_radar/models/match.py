"""Structured match analysis models."""

from typing import Literal

from pydantic import BaseModel, Field

RoleFit = Literal["high", "medium", "low", "unclear"]
MustHaveFit = Literal["yes", "partial", "no", "unclear"]
Recommendation = Literal["apply", "consider", "low_priority", "skip"]
Confidence = Literal["high", "medium", "low"]
AnalysisSource = Literal["deterministic", "ai", "ai_with_deterministic_overrides"]


class ScoringRubric(BaseModel):
    """Fixed scoring weights used by semantic match analysis."""

    role_alignment: int = 35
    skills_experience: int = 25
    eligibility: int = 20
    preferences_location: int = 10
    evidence_source_clarity: int = 10


class DeterministicMatchResult(BaseModel):
    """Program-owned match signals that do not require semantic judgment."""

    should_call_ai: bool = True
    hard_reject: bool = False
    score_cap: int | None = None
    recommendation_override: Recommendation | None = None
    match_reasons: list[str] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)


class SemanticMatchAssessment(BaseModel):
    """AI-produced semantic comparison before deterministic overrides."""

    match_score: int = Field(ge=0, le=100)
    role_fit: RoleFit
    must_have_fit: MustHaveFit
    match_reasons: list[str] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    job_summary: str
    recommendation: Recommendation
    confidence: Confidence


class FinalMatchAssessment(SemanticMatchAssessment):
    """Accepted match result after deterministic rules are applied."""

    analysis_source: AnalysisSource
    deterministic_reasons: list[str] = Field(default_factory=list)
