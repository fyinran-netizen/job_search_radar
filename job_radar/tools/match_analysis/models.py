"""Structured match analysis models."""

from typing import Literal

from pydantic import BaseModel, Field

RoleFit = Literal["high", "medium", "low", "unclear"]
MustHaveFit = Literal["yes", "partial", "no", "unclear"]
Recommendation = Literal["apply", "consider", "low_priority", "skip"]
Confidence = Literal["high", "medium", "low"]
AnalysisSource = Literal[
    "deterministic_only",
    "semantic_with_program_scoring",
]

class ScoringRubric(BaseModel):
    """Fixed scoring weights used by semantic match analysis."""

    role_alignment: int = 35
    requirement_fit: int = 25
    eligibility: int = 20
    location_preference: int = 10


class SemanticMatchAssessment(BaseModel):
    """AI-produced semantic comparison only.

    Score and recommendation are intentionally absent: they are calculated
    from this semantic evidence and structured facts by ``scoring.py``.
    """

    role_fit: RoleFit
    must_have_fit: MustHaveFit
    match_reasons: list[str] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    confidence: Confidence


class FinalMatchAssessment(SemanticMatchAssessment):
    """Final match result after deterministic rules are applied."""

    analysis_source: AnalysisSource
    deterministic_reasons: list[str] = Field(default_factory=list)
    score_components: dict[str, int] = Field(default_factory=dict)
    match_score: int = Field(ge=0, le=100)
    recommendation: Recommendation


