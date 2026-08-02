"""Tool interface used by agent workflows."""

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel


class BaseTool(ABC):
    """Base interface for deterministic or external tools."""

    name: str

    @abstractmethod
    def run(self, payload: BaseModel | dict[str, Any]) -> BaseModel | dict[str, Any] | list[Any]:
        """Run the tool with structured input."""
