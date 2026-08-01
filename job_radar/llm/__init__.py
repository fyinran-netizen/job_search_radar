"""LLM client abstractions."""

from job_radar.llm.base import LLMClient
from job_radar.llm.mock import MockLLMClient

__all__ = ["LLMClient", "MockLLMClient"]
