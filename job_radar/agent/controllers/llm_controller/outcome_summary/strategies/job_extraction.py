"""Mixed strategy for extraction quality and job semantic outcomes."""

import json

from job_radar.agent.models import AgentState
from job_radar.infra.llm.base import AIProvider
from job_radar.agent.controllers.llm_controller.outcome_summary.common import call_summary_llm, clip, deterministic_summary, fields, new_items


def summarize(before: AgentState, after: AgentState, provider: AIProvider | None, timeout_seconds: int) -> str:
    jobs = new_items(before.prepared_jobs, after.prepared_jobs, "deduplication_key")
    gate_projection = fields(jobs, ("title", "company_name", "locations", "basic_gate"))
    gate_passed = sum(job.basic_gate.should_continue for job in jobs)
    gate_text = f"Extraction produced {len(jobs)} new validated job records; {gate_passed} pass the basic eligibility gate."
    if not jobs:
        return deterministic_summary(gate_text + " No new job record is available for semantic evaluation.")
    semantic_projection = []
    for job in jobs:
        semantic_projection.append({
            "title": job.title,
            "company_name": job.company_name,
            "description": clip(job.description, 350),
            "requirements": clip(job.requirements, 350),
            "recruitment_type": job.recruitment_type,
            "locations": job.locations,
        })
    prompt = "\n".join([
        "Assess the semantic quality and decision usefulness of these newly extracted job records.",
        "Mention whether the roles are sufficiently specific and whether the evidence appears relevant for downstream understanding.",
        json.dumps(semantic_projection, ensure_ascii=False),
        '{"summary": "short semantic outcome"}',
    ])
    semantic_text = call_summary_llm(provider, prompt, timeout_seconds)
    if semantic_text is None:
        return deterministic_summary(gate_text + " The records provide candidate role and requirement evidence for downstream evaluation.")
    return deterministic_summary(gate_text + " " + semantic_text)


__all__ = ["summarize"]
