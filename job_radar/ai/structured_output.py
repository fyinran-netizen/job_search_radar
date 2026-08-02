"""Helpers for parsing and validating structured AI output."""

import json
import re
from typing import Any, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class StructuredOutputError(RuntimeError):
    """Raised when AI output cannot be parsed or validated."""


def parse_json_output(output: str) -> Any:
    """Parse JSON from AI output, allowing fenced JSON blocks."""

    text = output.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.S | re.I)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise StructuredOutputError(f"AI output was not valid JSON: {output[:1000]}") from exc


def validate_model(data: Any, model_type: type[T]) -> T:
    """Validate parsed data against a Pydantic model."""

    return model_type.model_validate(data)
