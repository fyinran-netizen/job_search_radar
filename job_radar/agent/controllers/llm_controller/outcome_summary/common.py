"""Shared helpers for action outcome summary strategies."""

from __future__ import annotations

from typing import Any, Iterable

from job_radar.agent.models import AgentState
from job_radar.infra.llm.base import AIProvider
from job_radar.infra.llm.structured_output import validate_model
from job_radar.agent.controllers.llm_controller.outcome_summary.models import ActionSemanticSummary


def new_items(before: list[Any], after: list[Any], key: str) -> list[Any]:
    prior = {_value(item, key) for item in before}
    return [item for item in after if _value(item, key) not in prior]


def new_values(before: Iterable[str], after: Iterable[str]) -> list[str]:
    prior = set(before)
    return [value for value in after if value not in prior]


def clip(value: str | None, limit: int = 500) -> str | None:
    if not value:
        return None
    return value[:limit] + ("…" if len(value) > limit else "")


def fields(items: Iterable[Any], names: tuple[str, ...]) -> list[dict[str, Any]]:
    result = []
    for item in items:
        data = item if isinstance(item, dict) else item.model_dump()
        result.append({name: data[name] for name in names if name in data and data[name] not in (None, "", [])})
    return result


def state_queries(state: AgentState) -> list[str]:
    return state.search_plan.queries if state.search_plan is not None else []


def call_summary_llm(provider: AIProvider | None, prompt: str, timeout_seconds: int) -> str | None:
    if provider is None:
        return None
    try:
        raw = provider.generate_json(
            prompt,
            timeout_seconds=timeout_seconds,
            system_prompt="Return one short structured summary of the supplied action outcome. Preserve semantic evidence; do not restate counts alone.",
        )
        return validate_model(raw, ActionSemanticSummary).summary
    except Exception:
        return None


def deterministic_summary(text: str) -> str:
    return text[:600]


def _value(item: Any, key: str) -> Any:
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


__all__ = ["call_summary_llm", "clip", "deterministic_summary", "fields", "new_items", "new_values", "state_queries"]
