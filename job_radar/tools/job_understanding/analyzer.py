"""AI job understanding for prepared job records."""

import json
from typing import Any

from job_radar.infra.llm.base import AIProvider
from job_radar.infra.llm.prompt_loader import load_runtime_prompt
from job_radar.infra.llm.structured_output import validate_model
from job_radar.tools.job_extraction.models import JobRecord
from job_radar.tools.job_understanding.models import (
    JobRequirementFacts,
    JobUnderstandingRecord,
)


class JobUnderstandingAnalyzer:
    """Produce structured semantic facts from one prepared job."""

    def __init__(
        self,
        provider: AIProvider,
        skill_name: str = "job-understanding",
        timeout_seconds: int = 180,
    ) -> None:
        self.provider = provider
        self.skill_name = skill_name
        self.timeout_seconds = timeout_seconds

    def understand(self, job: JobRecord) -> JobUnderstandingRecord:
        """Understand a job that has already passed the extraction-stage gate."""

        basic_gate = job.basic_gate
        if not basic_gate.should_continue:
            raise ValueError(
                "Job understanding received a job that did not pass Basic Gate."
            )

        system_prompt, user_prompt = self._build_prompts(job)

        data = self.provider.generate_json(
            user_prompt,
            timeout_seconds=self.timeout_seconds,
            system_prompt=system_prompt,
        )

        facts = validate_model(data, JobRequirementFacts)

        return JobUnderstandingRecord(
            deduplication_key=job.deduplication_key,
            basic_gate=basic_gate,
            understanding=facts,
            source="ai",
        )

    def _build_prompts(
        self,
        job: JobRecord,
    ) -> tuple[str, str]:
        skill = load_runtime_prompt(self.skill_name)

        schema = json.dumps(
            JobRequirementFacts.model_json_schema(),
            ensure_ascii=False,
            indent=2,
        )

        system_prompt = "\n\n".join(
            [
                "You are Job Radar's job requirement understanding component.",
                skill.instructions.strip(),
                "Return ONLY valid JSON matching the schema. Do not include Markdown or explanations.",
                f"Output schema:\n{schema}",
            ]
        )

        user_payload: dict[str, Any] = {
            "job": _job_payload(job),
        }

        return (
            system_prompt,
            "Input:\n" + json.dumps(user_payload, ensure_ascii=False, indent=2),
        )


def _job_payload(job: JobRecord) -> dict[str, Any]:
    return {
        "title": job.title,
        "description": job.description,
        "requirements": job.requirements,
        "recruitment_type": job.recruitment_type,
    }