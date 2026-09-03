"""Tool executor used by agent workflows."""

from time import perf_counter
from typing import Any

from pydantic import BaseModel

from job_radar.infra.logging import get_logger
from job_radar.tools.page_acquisition.models import ToolEvent
from job_radar.tools.base import BaseTool


logger = get_logger(__name__)


class ToolExecutor:
    """Dispatch named tool calls and keep an execution trace."""

    def __init__(self, tools: list[BaseTool]) -> None:
        self.tools = {tool.name: tool for tool in tools}
        if len(self.tools) != len(tools):
            raise ValueError("Tool names must be unique.")
        self.events: list[ToolEvent] = []

    def reset(self) -> None:
        """Clear the execution trace before a new agent run."""

        self.events = []

    def run(self, tool_name: str, payload: BaseModel | dict[str, Any]) -> BaseModel | dict[str, Any] | list[Any]:
        """Run a registered tool by name."""

        if tool_name not in self.tools:
            raise ValueError(f"Tool is not registered: {tool_name}")
        started = perf_counter()
        input_summary = self._summarize(payload)
        logger.info("tool_start tool=%s input=%s", tool_name, input_summary)
        try:
            result = self.tools[tool_name].run(payload)
        except Exception:
            logger.exception(
                "tool_failed tool=%s elapsed_ms=%.1f input=%s",
                tool_name,
                (perf_counter() - started) * 1000,
                input_summary,
            )
            raise
        elapsed_ms = (perf_counter() - started) * 1000
        self.events.append(
            ToolEvent(
                tool_name=tool_name,
                input_summary=self._summarize(payload),
                output_summary=self._summarize(result),
            )
        )
        logger.info(
            "tool_complete tool=%s elapsed_ms=%.1f output=%s",
            tool_name,
            elapsed_ms,
            self._summarize(result),
        )
        return result

    @staticmethod
    def _summarize(value: object) -> str:
        if isinstance(value, list):
            return f"list[{len(value)}]"
        summary = getattr(value, "tool_event_summary", None)
        if callable(summary):
            return str(summary())
        if isinstance(value, BaseModel):
            fetch_evidence = getattr(value, "fetch_evidence", None)
            fetch_method = getattr(fetch_evidence, "fetch_method", None)
            if fetch_method:
                return f"{value.__class__.__name__}(acquisition_method={fetch_method})"
            return value.__class__.__name__
        if isinstance(value, dict):
            return f"dict[{', '.join(sorted(value.keys()))}]"
        return value.__class__.__name__


