"""Mock AI provider for deterministic tests."""

from typing import Any

from job_radar.ai.providers.base import AIProvider


class MockAIProvider(AIProvider):
    """Return preconfigured JSON-compatible data."""

    def __init__(self, response: Any) -> None:
        self.response = response
        self.prompts: list[str] = []

    def generate_json(self, prompt: str, timeout_seconds: int = 180) -> Any:
        """Record the prompt and return the configured response."""

        self.prompts.append(prompt)
        return self.response
