"""Tool interface and dispatcher used by agent workflows."""

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel

from job_radar.agents.models import ToolEvent


class BaseTool(ABC):
    """Base interface for deterministic or external tools."""

    name: str

    @abstractmethod
    def run(self, payload: BaseModel | dict[str, Any]) -> BaseModel | dict[str, Any] | list[Any]:
        """Run the tool with structured input."""


class ToolScheduler:
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
        if isinstance(value, BaseModel):
            return value.__class__.__name__
        if isinstance(value, dict):
            return f"dict[{', '.join(sorted(value.keys()))}]"
        return value.__class__.__name__
