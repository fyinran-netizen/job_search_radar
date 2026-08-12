"""AI semantic match analysis for prepared job records."""

import json
from typing import Any

from job_radar.ai.providers.base import AIProvider
from job_radar.ai.skill_loader import load_skill
from job_radar.ai.structured_output import validate_model
from job_radar.models.job import JobRecord
from job_radar.models.match import (
    DeterministicMatchResult,
    FinalMatchAssessment,
    ScoringRubric,
    SemanticMatchAssessment,
)
from job_radar.models.profile import UserProfile
from job_radar.pipeline.deterministic_match import (
    build_deterministic_final,
    evaluate_deterministic_match,
    merge_match_results,
)


class SemanticMatchAnalyzer:
    """Run one semantic AI matching call per job and apply deterministic overrides."""

    def __init__(
        self,
        provider: AIProvider,
        skill_name: str = "match-analysis",
        rubric: ScoringRubric | None = None,
        timeout_seconds: int = 180,
    ) -> None:
        self.provider = provider
        self.skill_name = skill_name
        self.rubric = rubric or ScoringRubric()
        self.timeout_seconds = timeout_seconds

    def analyze(self, job: JobRecord, profile: UserProfile) -> FinalMatchAssessment:
        """Analyze one job against a profile."""

        deterministic = evaluate_deterministic_match(job, profile)
        if not deterministic.should_call_ai:
            return build_deterministic_final(job, deterministic)

        system_prompt, user_prompt = self._build_prompts(job, profile, deterministic)
        data = self.provider.generate_json(
            user_prompt,
            timeout_seconds=self.timeout_seconds,
            system_prompt=system_prompt,
        )
        semantic = validate_model(data, SemanticMatchAssessment)
        return merge_match_results(semantic, deterministic)

    def _build_prompts(
        self,
        job: JobRecord,
        profile: UserProfile,
        deterministic: DeterministicMatchResult,
    ) -> tuple[str, str]:
        skill = load_skill(self.skill_name)
        schema = json.dumps(SemanticMatchAssessment.model_json_schema(), ensure_ascii=False, indent=2)
        system_prompt = "\n\n".join(
            [
                "You are Job Radar's semantic match analysis component.",
                skill.instructions.strip(),
                "Program-owned deterministic checks take priority over your semantic judgment.",
                "Use the fixed scoring rubric exactly; do not invent new scoring categories.",
                "Return ONLY valid JSON matching the schema. Do not include Markdown or explanations.",
                f"Output schema:\n{schema}",
            ]
        )
        user_payload: dict[str, Any] = {
            "candidate_profile": profile.model_dump(),
            "prepared_job": _job_payload(job),
            "deterministic_signals": deterministic.model_dump(),
            "scoring_rubric": self.rubric.model_dump(),
            "recommendation_scale": {
                "apply": "Strong semantic fit and enough evidence.",
                "consider": "Plausible fit, but not clearly top priority.",
                "low_priority": "Weak fit or important uncertainty.",
                "skip": "Poor semantic fit or clear disqualifying concern.",
            },
            "instructions": [
                "Assess semantic fit once; do not ask for more context.",
                "Keep match_score between 0 and 100.",
                "Be conservative when the job description is vague.",
                "Do not override deterministic hard facts, risk flags, or score caps.",
                "Put uncertainty in missing_requirements or risk_flags rather than guessing.",
            ],
        }
        return system_prompt, "Input:\n" + json.dumps(user_payload, ensure_ascii=False, indent=2)


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
        "published_at": job.published_at,
        "deadline": job.deadline,
        "source_name": job.source_name,
        "is_official": job.is_official,
        "rule_based_match_score": job.match_score,
        "rule_based_match_reasons": job.match_reasons,
        "rule_based_missing_requirements": job.missing_requirements,
    }
