"""Program-owned gate models for deterministic checks before AI tasks."""

from typing import Literal

from pydantic import BaseModel, Field

GateDecision = Literal["continue", "skip"]
GateSource = Literal["program_basic_gate"]


class BasicGateResult(BaseModel):
    """Deterministic checks that can run before job understanding."""

    decision: GateDecision = "continue"
    hard_reject: bool = False
    score_cap: int | None = None
    recommendation_override: str | None = None
    gate_reasons: list[str] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    source: GateSource = "program_basic_gate"

    @property
    def should_continue(self) -> bool:
        """Return whether downstream AI understanding should run."""

        return self.decision == "continue"

    @property
    def should_call_ai(self) -> bool:
        """Compatibility alias for older matching code."""

        return self.should_continue

    @property
    def match_reasons(self) -> list[str]:
        """Compatibility alias for older matching code."""

        return self.gate_reasons
