"""Structured match analysis models."""

from typing import Literal

from pydantic import BaseModel, Field

from job_radar.models.gate import BasicGateResult

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


DeterministicMatchResult = BasicGateResult


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
    """Final match result after deterministic rules are applied."""

    analysis_source: AnalysisSource
    deterministic_reasons: list[str] = Field(default_factory=list)
