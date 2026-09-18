"""AI semantic match analysis for prepared job records."""

import json
import logging
from typing import Any

from job_radar.infra.llm.base import AIProvider
from job_radar.infra.llm.prompt_loader import load_runtime_prompt
from job_radar.infra.llm.structured_output import validate_model
from job_radar.tools.job_extraction.models import JobRecord
from job_radar.tools.match_analysis.models import FinalMatchAssessment, ScoringRubric, SemanticMatchAssessment
from job_radar.profile.models import UserProfile
from job_radar.tools.job_understanding.models import JobRequirementFacts, JobUnderstandingRecord
from job_radar.tools.match_analysis.scoring import build_final_assessment


logger = logging.getLogger(__name__)


class SemanticMatchAnalyzer:
    """Run the one semantic comparison call; scoring is deterministic."""

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

    def analyze_understanding(self, record: JobUnderstandingRecord, job: JobRecord, profile: UserProfile) -> FinalMatchAssessment:
        """Analyze one understood job against a profile."""

        basic_gate = record.basic_gate
        logger.info("match_analysis gate title=%s graduation=%s deadline=%s decision=%s hard_reject=%s reasons=%s", job.title, profile.graduation_date, job.deadline, basic_gate.decision, basic_gate.hard_reject, "; ".join(basic_gate.gate_reasons))
        if not basic_gate.should_continue:
            final = build_final_assessment(job, record.understanding, None, profile, basic_gate, self.rubric)
            logger.info("match_analysis final title=%s score=%s decision=%s", job.title, final.match_score, final.recommendation)
            return final

        system_prompt, user_prompt = self._build_prompts(job, profile, record.understanding)
        data = self.provider.generate_json(
            user_prompt,
            timeout_seconds=self.timeout_seconds,
            system_prompt=system_prompt,
        )
        semantic = validate_model(data, SemanticMatchAssessment)
        final = build_final_assessment(job, record.understanding, semantic, profile, basic_gate, self.rubric)
        logger.info("match_analysis final title=%s score=%s decision=%s", job.title, final.match_score, final.recommendation)
        return final

    def _build_prompts(
        self,
        job: JobRecord,
        profile: UserProfile,
        understanding: JobRequirementFacts | None,
    ) -> tuple[str, str]:
        skill = load_runtime_prompt(self.skill_name)
        schema = json.dumps(SemanticMatchAssessment.model_json_schema(), ensure_ascii=False, indent=2)
        system_prompt = "\n\n".join(
            [
                "You are Job Radar's semantic match analysis component.",
                skill.instructions.strip(),
                "Return semantic role alignment and requirement fit only. Program code owns eligibility, scoring, and recommendation.",
                "Return ONLY valid JSON matching the schema. Do not include Markdown or explanations.",
                f"Output schema:\n{schema}",
            ]
        )
        user_payload: dict[str, Any] = {
            "candidate_profile": {
                "education": profile.education,
                "target_roles": profile.target_roles,
                "skills": profile.skills,
            },
            "job": _job_payload(job),
            "job_understanding": understanding.model_dump() if understanding else None,
            "instructions": [
                "Assess role alignment and must-have requirement fit once.",
                "Be conservative when the job description is vague.",
                "Put uncertainty in missing_requirements or risk_flags rather than guessing.",
            ],
        }
        return system_prompt, "Input:\n" + json.dumps(user_payload, ensure_ascii=False, indent=2)


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
        "source_name": job.source_name,
        "is_official": job.is_official,
    }
