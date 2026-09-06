"""AI job understanding for prepared job records."""

import json
from typing import Any

from job_radar.infra.llm.base import AIProvider
from job_radar.infra.llm.prompt_loader import load_runtime_prompt
from job_radar.infra.llm.structured_output import validate_model
from job_radar.tools.job_extraction.models import BasicGateResult
from job_radar.tools.job_extraction.models import JobRecord
from job_radar.profile.models import UserProfile
from job_radar.tools.job_understanding.models import JobRequirementFacts, JobUnderstandingRecord


class JobUnderstandingAnalyzer:
    """Produce discipline-neutral structured facts from one prepared job."""

    def __init__(
        self,
        provider: AIProvider,
        skill_name: str = "job-understanding",
        timeout_seconds: int = 180,
    ) -> None:
        self.provider = provider
        self.skill_name = skill_name
        self.timeout_seconds = timeout_seconds

    def understand(self, job: JobRecord, profile: UserProfile) -> JobUnderstandingRecord:
        """Understand a job that has already passed the extraction-stage gate."""

        basic_gate = job.basic_gate
        if not basic_gate.should_continue:
            raise ValueError("Job understanding received a job that did not pass Basic Gate.")

        system_prompt, user_prompt = self._build_prompts(job, profile, basic_gate)
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
        profile: UserProfile,
        basic_gate: BasicGateResult,
    ) -> tuple[str, str]:
        skill = load_runtime_prompt(self.skill_name)
        schema = json.dumps(JobRequirementFacts.model_json_schema(), ensure_ascii=False, indent=2)
        system_prompt = "\n\n".join(
            [
                "You are Job Radar's job requirement understanding component.",
                skill.instructions.strip(),
                "Return ONLY valid JSON matching the schema. Do not include Markdown or explanations.",
                f"Output schema:\n{schema}",
            ]
        )
        user_payload: dict[str, Any] = {
            "candidate_profile_context": _profile_context(profile),
            "prepared_job": _job_payload(job),
            "program_basic_gate": basic_gate.model_dump(),
            "instructions": [
                "Understand the job itself; do not calculate candidate match score or recommendation.",
                "Use discipline-neutral categories. Do not assume requirements are technical skills.",
                "Separate hard requirements from preferences and contextual information.",
                "Keep wording grounded in evidence from title, description, requirements, and metadata.",
                "When text is vague, set confidence lower and put uncertainty in risk_flags.",
            ],
        }
        return system_prompt, "Input:\n" + json.dumps(user_payload, ensure_ascii=False, indent=2)


def _profile_context(profile: UserProfile) -> dict[str, object]:
    return {
        "education": profile.education,
        "graduation_date": profile.graduation_date,
        "target_roles": profile.target_roles,
        "preferred_locations": profile.preferred_locations,
        "excluded_locations": profile.excluded_locations,
    }


def _job_payload(job: JobRecord) -> dict[str, Any]:
    return {
        "company_name": job.company_name,
        "company_type": job.company_type,
        "title": job.title,
        "locations": job.locations,
        "description": job.description,
        "requirements": job.requirements,
        "recruitment_type": job.recruitment_type,
        "graduation_years": job.graduation_years,
        "graduation_start": job.graduation_start,
        "graduation_end": job.graduation_end,
        "graduation_requirement": job.graduation_requirement,
        "deadline": job.deadline,
        "education_levels": job.education_levels,
        "apply_url": job.apply_url,
        "source_url": job.source_url,
        "source_name": job.source_name,
        "is_official": job.is_official,
    }
