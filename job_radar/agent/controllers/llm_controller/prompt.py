"""Prompt construction for the workflow controller model."""

from __future__ import annotations

import json
from copy import deepcopy
from collections.abc import Mapping, Sequence

from job_radar.agent.action_names import AgentActionName
from job_radar.agent.action_semantics import (
    ActionSemantics,
    get_available_action_semantics,
)
from job_radar.agent.controllers.llm_controller.models import LLMControllerDecision
from job_radar.agent.controllers.llm_controller.observation.models import ControllerObservation


def build_controller_system_prompt() -> str:
    """Build the fixed instructions shared by every controller decision."""

    return "\n".join([
        "You are a bounded workflow controller.",
        "Choose exactly one action from the available_actions provided in the user message.",
        "Do not generate tool arguments.",
        "Do not modify state.",
        "Return structured JSON matching the provided output schema.",
        'If action == "stop", stop_reason must be a non-empty string.',
        'If action != "stop", stop_reason must be null.',
    ])


def build_controller_output_schema(
    available_actions: Sequence[AgentActionName],
) -> dict[str, object]:
    """Return the final decision schema with action constrained to this namespace."""

    schema = deepcopy(LLMControllerDecision.model_json_schema())
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        raise ValueError("LLMControllerDecision schema has no properties")
    action_schema = properties.get("action")
    if not isinstance(action_schema, dict):
        raise ValueError("LLMControllerDecision schema has no action property")
    action_schema["enum"] = list(dict.fromkeys(available_actions))
    return schema


def build_controller_prompt(
    observation: ControllerObservation,
    available_actions: Sequence[AgentActionName],
    action_semantics: Mapping[AgentActionName, ActionSemantics] | None = None,
) -> str:
    """Build the namespace-scoped user prompt for one controller decision."""

    scoped_semantics = (
        action_semantics
        if action_semantics is not None
        else get_available_action_semantics(available_actions)
    )

    return "\n\n".join([
        f"Available actions:\n{json.dumps(list(available_actions), ensure_ascii=False, indent=2)}",
        "Action semantics:\n" + json.dumps(
            {action: semantics.model_dump() for action, semantics in scoped_semantics.items()},
            ensure_ascii=False,
            indent=2,
        ),
        f"Observation:\n{observation.model_dump_json(indent=2)}",
        f"Output schema:\n{json.dumps(build_controller_output_schema(available_actions), ensure_ascii=False, indent=2)}",
    ])


__all__ = [
    "build_controller_output_schema",
    "build_controller_prompt",
    "build_controller_system_prompt",
]
