"""Build prompts from skill documents, data, and output schemas."""

import json
from typing import Any

from pydantic import BaseModel

from job_radar.infra.llm.prompt_loader import SkillDocument


def build_json_prompt(skill: SkillDocument, payload: dict[str, Any], output_model: type[BaseModel] | None = None) -> str:
    """Build a prompt that asks the provider to return only JSON."""

    schema_text = ""
    if output_model is not None:
        schema_text = json.dumps(output_model.model_json_schema(), ensure_ascii=False, indent=2)
    payload_text = json.dumps(payload, ensure_ascii=False, indent=2)
    return "\n\n".join(
        part
        for part in [
            skill.instructions.strip(),
            skill.examples.strip(),
            "Return ONLY valid JSON. Do not include Markdown or explanations.",
            f"Output schema:\n{schema_text}" if schema_text else "",
            f"Input:\n{payload_text}",
        ]
        if part
    )


