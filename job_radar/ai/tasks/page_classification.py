"""AI page classification before job extraction."""

from typing import Literal

from pydantic import BaseModel, Field

from job_radar.ai.prompt_builder import build_json_prompt
from job_radar.ai.providers.base import AIProvider
from job_radar.ai.skill_loader import load_skill
from job_radar.ai.tasks.job_extraction import AIPageInput
from job_radar.ai.structured_output import validate_model
from job_radar.models.page_triage import PendingKind, SuggestedNextAction


class PageJDClassification(BaseModel):
    """Decision about whether a page is a concrete job detail page."""

    is_job_detail_page: bool
    pending_kind: PendingKind | None = None
    suggested_next_action: SuggestedNextAction | None = None
    reasons: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "low"


class PageJDClassifier:
    """Classify pages as concrete JD pages before extraction."""

    def __init__(
        self,
        provider: AIProvider,
        skill_name: str = "page-jd-classification",
        max_text_chars: int = 6000,
        timeout_seconds: int = 90,
    ) -> None:
        self.provider = provider
        self.skill_name = skill_name
        self.max_text_chars = max_text_chars
        self.timeout_seconds = timeout_seconds

    def classify(self, page: AIPageInput) -> PageJDClassification:
        """Return whether a page is clearly a single job detail page."""

        skill = load_skill(self.skill_name)
        prompt = build_json_prompt(
            skill,
            {
                "page": {
                    "title": page.title,
                    "visible_text": page.visible_text[: self.max_text_chars],
                    "important_links": [link.model_dump() for link in page.important_links],
                },
            },
            output_model=PageJDClassification,
        )
        data = self.provider.generate_json(prompt, timeout_seconds=self.timeout_seconds)
        classification = validate_model(data, PageJDClassification)
        if classification.is_job_detail_page:
            return PageJDClassification(
                is_job_detail_page=True,
                reasons=classification.reasons,
                evidence=classification.evidence,
                confidence=classification.confidence,
            )
        return classification
