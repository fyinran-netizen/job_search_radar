"""AI-backed job extraction task with minimal page input."""

from pydantic import BaseModel, Field, TypeAdapter

from job_radar.ai.prompt_builder import build_json_prompt
from job_radar.ai.providers.base import AIProvider
from job_radar.ai.skill_loader import load_skill
from job_radar.models.job import RawJobRecord
from job_radar.models.tool import PageContent


class AIPageInput(BaseModel):
    """Minimal page payload sent to AI extraction."""

    url: str
    final_url: str | None = None
    title: str
    visible_text: str = Field(description="Cleaned visible page text, truncated before prompting.")


def build_ai_page_input(page: PageContent, max_text_chars: int = 12000) -> AIPageInput:
    """Trim collected page content to the fields AI extraction actually needs."""

    final_url = page.metadata.get("final_url")
    return AIPageInput(
        url=page.url,
        final_url=final_url if isinstance(final_url, str) else None,
        title=page.title,
        visible_text=_clean_text(page.text)[:max_text_chars],
    )


class AIJobExtractionClient:
    """Extract RawJobRecord objects from PageContent through a structured AI provider."""

    def __init__(
        self,
        provider: AIProvider,
        skill_name: str = "job-extraction",
        max_text_chars: int = 12000,
        timeout_seconds: int = 240,
    ) -> None:
        self.provider = provider
        self.skill_name = skill_name
        self.max_text_chars = max_text_chars
        self.timeout_seconds = timeout_seconds

    def extract_jobs_from_page(self, page: PageContent) -> list[RawJobRecord]:
        """Build a minimal prompt payload and validate RawJobRecord[] output."""

        payload = build_ai_page_input(page, max_text_chars=self.max_text_chars)
        skill = load_skill(self.skill_name)
        prompt = build_json_prompt(
            skill,
            {
                "page": payload.model_dump(),
                "output": "Return a JSON array of RawJobRecord objects.",
            },
        )
        data = self.provider.generate_json(prompt, timeout_seconds=self.timeout_seconds)
        return TypeAdapter(list[RawJobRecord]).validate_python(data)


def _clean_text(text: str) -> str:
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)
