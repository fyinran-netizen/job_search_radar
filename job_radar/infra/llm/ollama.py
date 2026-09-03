"""Ollama provider for structured local or cloud-model JSON calls."""

from __future__ import annotations

import json
from time import perf_counter
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from job_radar.infra.llm.base import AIProvider
from job_radar.infra.llm.structured_output import StructuredOutputError, parse_json_output
from job_radar.infra.logging import get_logger

logger = get_logger(__name__)


class OllamaError(RuntimeError):
    """Raised when Ollama cannot return valid structured JSON."""


class OllamaProvider(AIProvider):
    """Call the local Ollama HTTP API and parse JSON from the model response."""

    def __init__(
        self,
        model: str = "qwen3.5:cloud",
        base_url: str = "http://localhost:11434",
        temperature: float = 0.0,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/") + "/"
        self.temperature = temperature

    def is_available(self, timeout_seconds: int = 10) -> bool:
        """Return whether the local Ollama server is reachable."""

        try:
            with urlopen(urljoin(self.base_url, "api/version"), timeout=timeout_seconds) as response:
                return 200 <= response.status < 300
        except (OSError, HTTPError, URLError):
            return False

    def generate_json(self, prompt: str, timeout_seconds: int = 180, system_prompt: str | None = None) -> Any:
        """Call Ollama chat and parse the assistant message as JSON."""

        messages = []
        if system_prompt:
            messages.append(
                {
                    "role": "system",
                    "content": system_prompt,
                }
            )
        messages.append(
            {
                "role": "user",
                "content": prompt,
            }
        )
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "format": "json",
            "think": "low" if self.model.lower().startswith("gpt-oss") else False,
            "options": {
                "temperature": self.temperature,
            },
        }
        request = Request(
            urljoin(self.base_url, "api/chat"),
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        started = perf_counter()
        endpoint = urljoin(self.base_url, "api/chat")
        logger.info("llm_request_start provider=ollama model=%s endpoint=%s timeout_seconds=%s", self.model, endpoint, timeout_seconds)
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
            logger.info("llm_request_complete provider=ollama model=%s elapsed_ms=%.1f response_connection=closed", self.model, (perf_counter() - started) * 1000)
        except (OSError, HTTPError, URLError, json.JSONDecodeError) as exc:
            logger.exception("llm_request_failed provider=ollama model=%s elapsed_ms=%.1f", self.model, (perf_counter() - started) * 1000)
            raise OllamaError(f"Ollama request failed: {exc}") from exc

        message = response_payload.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise OllamaError("Ollama response did not include message.content.")
        try:
            return parse_json_output(content)
        except StructuredOutputError as exc:
            raise OllamaError(str(exc)) from exc


