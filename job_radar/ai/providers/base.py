"""Provider interface for structured AI calls."""

from abc import ABC, abstractmethod
from typing import Any


class AIProvider(ABC):
    """Generate structured JSON-compatible data from a prompt."""

    @abstractmethod
    def generate_json(self, prompt: str, timeout_seconds: int = 180) -> Any:
        """Return parsed JSON-compatible data for a prompt."""
