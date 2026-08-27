"""Tool executor used by agent workflows."""

from typing import Any

from pydantic import BaseModel

from job_radar.models.tool import ToolEvent
from job_radar.tools.base import BaseTool


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
        result = self.tools[tool_name].run(payload)
        self.events.append(
            ToolEvent(
                tool_name=tool_name,
                input_summary=self._summarize(payload),
                output_summary=self._summarize(result),
            )
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
            return value.__class__.__name__
        if isinstance(value, dict):
            return f"dict[{', '.join(sorted(value.keys()))}]"
        return value.__class__.__name__
