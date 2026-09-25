"""Factories for the runtime dependencies used by the agent graph."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from job_radar.config import load_runtime_settings
from job_radar.infra.llm.base import AIProvider
from job_radar.infra.llm.ollama import OllamaProvider
from job_radar.tools.executor import ToolExecutor
from job_radar.tools.registry import create_real_search_tool_executor


@dataclass(frozen=True)
class AgentRuntime:
    """Resolved, injectable dependencies for one real agent run."""

    executor: ToolExecutor
    metadata: dict[str, Any]


def create_real_agent_runtime() -> AgentRuntime:
    """Create the configured Ollama providers and the bounded tool executor."""

    settings = load_runtime_settings()
    metadata: dict[str, Any] = {
        "web_search_provider": "tavily",
        "page_acquisition_provider": "http",
        "analyze_page_model": settings.analyze_page.model,
        "extraction_model": settings.extraction.model,
        "understanding_model": settings.understanding.model,
        "match_model": settings.match.model,
        "ollama_base_url": settings.ollama_base_url,
    }
    providers: dict[str, AIProvider] = {
        key: OllamaProvider(model=str(metadata[model_key]), base_url=str(metadata["ollama_base_url"]))
        for key, model_key in {
            "analyze_page": "analyze_page_model",
            "job_extraction": "extraction_model",
            "job_understanding": "understanding_model",
            "match_analysis": "match_model",
        }.items()
    }
    if not all(provider.is_available() for provider in providers.values()):
        raise RuntimeError(f"Ollama server is not reachable at {metadata['ollama_base_url']}.")
    return AgentRuntime(
        executor=create_real_search_tool_executor(
            analyze_page_provider=providers["analyze_page"],
            job_extraction_provider=providers["job_extraction"],
            job_understanding_provider=providers["job_understanding"],
            match_analysis_provider=providers["match_analysis"],
        ),
        metadata=metadata,
    )


__all__ = ["AgentRuntime", "create_real_agent_runtime"]
