"""AI job understanding for prepared job records."""

import json
from typing import Any

from job_radar.ai.providers.base import AIProvider
from job_radar.ai.skill_loader import load_skill
from job_radar.ai.structured_output import validate_model
from job_radar.models.gate import BasicGateResult
from job_radar.models.job import JobRecord
from job_radar.models.profile import UserProfile
from job_radar.models.understanding import JobRequirementFacts, JobUnderstandingRecord
from job_radar.pipeline.basic_gate import evaluate_basic_gate


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
        """Run the basic gate, then understand one job if it remains eligible."""

        basic_gate = evaluate_basic_gate(job, profile)
        if not basic_gate.should_continue:
            return _skipped_record(job, basic_gate)

        system_prompt, user_prompt = self._build_prompts(job, profile, basic_gate)
        data = self.provider.generate_json(
            user_prompt,
            timeout_seconds=self.timeout_seconds,
            system_prompt=system_prompt,
        )
        facts = validate_model(data, JobRequirementFacts)
        return JobUnderstandingRecord(
            deduplication_key=job.deduplication_key,
            company_name=job.company_name or "",
            title=job.title or "",
            job=job,
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
        skill = load_skill(self.skill_name)
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


def _skipped_record(job: JobRecord, basic_gate: BasicGateResult) -> JobUnderstandingRecord:
    return JobUnderstandingRecord(
        deduplication_key=job.deduplication_key,
        company_name=job.company_name or "",
        title=job.title or "",
        job=job,
        basic_gate=basic_gate,
        understanding=None,
        source="skipped_by_basic_gate",
    )


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
        "location": job.location,
        "description": job.description,
        "requirements": job.requirements,
        "recruitment_type": job.recruitment_type,
        "graduation_years": job.graduation_years,
        "graduation_start": job.graduation_start,
        "graduation_end": job.graduation_end,
        "graduation_requirement": job.graduation_requirement,
        "start_date": job.start_date,
        "start_date_text": job.start_date_text,
        "published_at": job.published_at,
        "deadline": job.deadline,
        "apply_url": job.apply_url,
        "source_url": job.source_url,
        "source_name": job.source_name,
        "is_official": job.is_official,
    }
