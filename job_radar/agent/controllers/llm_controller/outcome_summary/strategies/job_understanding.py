"""Mixed strategy for requirement-understanding outcomes."""

import json

from job_radar.agent.models import AgentState
from job_radar.infra.llm.base import AIProvider
from job_radar.tools.job_understanding.models import JobRequirementFacts
from job_radar.agent.controllers.llm_controller.outcome_summary.common import (
    call_summary_llm,
    deterministic_summary,
    new_items,
)


def summarize(
    before: AgentState,
    after: AgentState,
    provider: AIProvider | None,
    timeout_seconds: int,
) -> str:
    records = new_items(
        before.understanding_records,
        after.understanding_records,
        "deduplication_key",
    )

    if not records:
        return deterministic_summary(
            "No new requirement-understanding records were produced for matching."
        )

    understood = [
        record for record in records
        if record.understanding is not None
    ]
    missing_count = len(records) - len(understood)

    if not understood:
        return deterministic_summary(
            f"{missing_count} new job(s) lack substantive understanding for matching."
        )

    role_names = [
        record.understanding.canonical_role.strip().casefold()
        for record in understood
        if record.understanding.canonical_role.strip()
    ]
    role_concentration = _role_concentration_level(role_names)

    projection = [
        _understanding_projection(record.understanding)
        for record in understood
    ]

    prompt = "\n".join([
        "Summarize the semantic meaning of these job-understanding results for candidate matching.",
        "Focus on role patterns, seniority, major requirements, responsibilities, work context, risks, confidence, and information sufficiency.",
        f"Use this deterministic role-concentration assessment as context: {role_concentration}.",
        "Explain meaningful similarities or differences across the understood jobs when supported by the supplied data.",
        "Do not mention record identifiers or basic eligibility gates.",
        "Do not infer requirements or job characteristics that are not present in the supplied understanding data.",
        json.dumps(projection, ensure_ascii=False),
        '{"summary": "short semantic outcome"}',
    ])

    semantic = call_summary_llm(
        provider,
        prompt,
        timeout_seconds,
    )

    deterministic_parts: list[str] = []

    if missing_count:
        deterministic_parts.append(
            f"{missing_count} new job(s) lack substantive understanding."
        )

    if role_concentration != "low":
        deterministic_parts.append(
            f"The understood roles show {role_concentration} concentration."
        )

    if semantic:
        deterministic_parts.append(semantic)

    if not deterministic_parts:
        return deterministic_summary(
            "The understood jobs provide structured role and requirement evidence for matching."
        )

    return deterministic_summary(" ".join(deterministic_parts))


def _understanding_projection(
    understanding: JobRequirementFacts,
) -> dict[str, object]:
    return {
        "canonical_role": understanding.canonical_role,
        "role_family": understanding.role_family,
        "seniority": understanding.seniority,
        "responsibilities": understanding.responsibilities,
        "requirements": [
            {
                "category": item.category,
                "text": item.text,
            }
            for item in understanding.requirements
        ],
        "work_context": understanding.work_context,
        "risk_flags": understanding.risk_flags,
        "confidence": understanding.confidence,
    }


def _role_concentration_level(role_names: list[str]) -> str:
    if len(role_names) < 2:
        return "low"

    unique_roles = len(set(role_names))
    concentration_ratio = 1 - (unique_roles / len(role_names))

    if concentration_ratio >= 0.5:
        return "high"
    if concentration_ratio > 0:
        return "moderate"
    return "low"


__all__ = ["summarize"]
