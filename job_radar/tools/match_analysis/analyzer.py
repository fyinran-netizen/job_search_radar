"""AI semantic match analysis for prepared job records."""

import json
import logging
from typing import Any

from job_radar.infra.llm.base import AIProvider
from job_radar.infra.llm.prompt_loader import load_runtime_prompt
from job_radar.infra.llm.structured_output import validate_model
from job_radar.tools.job_extraction.models import JobRecord
from job_radar.tools.match_analysis.models import BasicGateResult
from job_radar.tools.match_analysis.models import FinalMatchAssessment, ScoringRubric, SemanticMatchAssessment
from job_radar.profile.models import UserProfile
from job_radar.tools.job_understanding.models import JobRequirementFacts, JobUnderstandingRecord
from job_radar.tools.match_analysis.deterministic import (
    build_deterministic_final,
    evaluate_deterministic_match,
    merge_match_results,
)


logger = logging.getLogger(__name__)


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

        basic_gate = evaluate_deterministic_match(job, profile)
        logger.info("match_analysis gate title=%s graduation=%s deadline=%s decision=%s hard_reject=%s reasons=%s", job.title, profile.graduation_date, job.deadline, basic_gate.decision, basic_gate.hard_reject, "; ".join(basic_gate.gate_reasons))
        if not basic_gate.should_continue:
            final = build_deterministic_final(job, basic_gate)
            logger.info("match_analysis final title=%s score=%s decision=%s", job.title, final.match_score, final.recommendation)
            return final

        system_prompt, user_prompt = self._build_prompts(job, profile, basic_gate, None)
        data = self.provider.generate_json(
            user_prompt,
            timeout_seconds=self.timeout_seconds,
            system_prompt=system_prompt,
        )
        semantic = validate_model(data, SemanticMatchAssessment)
        final = merge_match_results(semantic, basic_gate)
        logger.info("match_analysis final title=%s score=%s decision=%s", job.title, final.match_score, final.recommendation)
        return final

    def analyze_understanding(self, record: JobUnderstandingRecord, job: JobRecord, profile: UserProfile) -> FinalMatchAssessment:
        """Analyze one understood job against a profile."""

        basic_gate = record.basic_gate
        logger.info("match_analysis gate title=%s graduation=%s deadline=%s decision=%s hard_reject=%s reasons=%s", job.title, profile.graduation_date, job.deadline, basic_gate.decision, basic_gate.hard_reject, "; ".join(basic_gate.gate_reasons))
        if not basic_gate.should_continue:
            final = build_deterministic_final(job, basic_gate)
            logger.info("match_analysis final title=%s score=%s decision=%s", job.title, final.match_score, final.recommendation)
            return final

        system_prompt, user_prompt = self._build_prompts(job, profile, basic_gate, record.understanding)
        data = self.provider.generate_json(
            user_prompt,
            timeout_seconds=self.timeout_seconds,
            system_prompt=system_prompt,
        )
        semantic = validate_model(data, SemanticMatchAssessment)
        final = merge_match_results(semantic, basic_gate)
        logger.info("match_analysis final title=%s score=%s decision=%s", job.title, final.match_score, final.recommendation)
        return final

    def _build_prompts(
        self,
        job: JobRecord,
        profile: UserProfile,
        basic_gate: BasicGateResult,
        understanding: JobRequirementFacts | None,
    ) -> tuple[str, str]:
        skill = load_runtime_prompt(self.skill_name)
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
            "job_understanding": understanding.model_dump() if understanding else None,
            "program_basic_gate": basic_gate.model_dump(),
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
        "graduation_start": job.graduation_start,
        "graduation_end": job.graduation_end,
        "graduation_requirement": job.graduation_requirement,
        "start_date": job.start_date,
        "start_date_text": job.start_date_text,
        "published_at": job.published_at,
        "deadline": job.deadline,
        "source_name": job.source_name,
        "is_official": job.is_official,
    }
