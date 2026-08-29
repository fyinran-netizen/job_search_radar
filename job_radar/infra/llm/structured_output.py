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
        repaired = _repair_trailing_json_containers(text, exc)
        if repaired is not None:
            try:
                return json.loads(repaired)
            except json.JSONDecodeError:
                pass
        raise StructuredOutputError(f"AI output was not valid JSON: {output[:1000]}") from exc


def _repair_trailing_json_containers(text: str, error: json.JSONDecodeError) -> str | None:
    """Repair only missing or misordered container closers at the end of JSON."""

    stripped_length = len(text.rstrip())
    if error.pos < stripped_length - 1:
        return None

    stack: list[str] = []
    repaired: list[str] = []
    in_string = False
    escaped = False
    for index, character in enumerate(text):
        repaired.append(character)
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character == "{":
            stack.append("}")
        elif character == "[":
            stack.append("]")
        elif character in "}]":
            if not stack:
                return None
            if stack[-1] != character:
                remaining = text[index:]
                if not re.fullmatch(r"[}\]\s]+", remaining) or character not in stack:
                    return None
                repaired.pop()
                while stack and stack[-1] != character:
                    repaired.append(stack.pop())
                repaired.append(character)
            stack.pop()

    if in_string:
        return None
    repaired.extend(reversed(stack))
    repaired_text = "".join(repaired)
    return repaired_text if repaired_text != text else None


def validate_model(data: Any, model_type: type[T]) -> T:
    """Validate parsed data against a Pydantic model."""

    return model_type.model_validate(data)


