"""Mixed strategy for fit and prioritization outcomes."""

import json
from collections import Counter
from typing import Any

from job_radar.agent.models import AgentState
from job_radar.infra.llm.base import AIProvider
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
    assessments = new_items(
        before.match_assessments,
        after.match_assessments,
        "deduplication_key",
    )

    if not assessments:
        return deterministic_summary(
            "No new fit assessment evidence was produced for prioritization."
        )

    deterministic_context = _deterministic_context(assessments)
    projection = [
        _semantic_projection(assessment)
        for assessment in assessments
    ]

    prompt = "\n".join([
        "Summarize what these new match assessments mean for opportunity prioritization.",
        "Identify the main recurring strengths, gaps, missing requirements, and risks.",
        "Explain which kinds of opportunities appear stronger or weaker when supported by the supplied evidence.",
        "Use the structured fit, recommendation, score, and confidence distributions as context, but do not simply repeat them.",
        "Do not infer candidate abilities or job requirements that are not present in the assessments.",
        f"Deterministic context:\n{json.dumps(deterministic_context, ensure_ascii=False)}",
        f"Assessment evidence:\n{json.dumps(projection, ensure_ascii=False)}",
        '{"summary": "short semantic outcome"}',
    ])

    semantic = call_summary_llm(
        provider,
        prompt,
        timeout_seconds,
    )

    if semantic:
        return semantic

    return deterministic_summary(
        _fallback_summary(assessments)
    )


def _semantic_projection(
    assessment: dict[str, Any],
) -> dict[str, Any]:
    return {
        "role_fit": assessment.get("role_fit"),
        "must_have_fit": assessment.get("must_have_fit"),
        "recommendation": assessment.get("recommendation"),
        "confidence": assessment.get("confidence"),
        "match_reasons": assessment.get("match_reasons", []),
        "missing_requirements": assessment.get("missing_requirements", []),
        "risk_flags": assessment.get("risk_flags", []),
    }


def _deterministic_context(
    assessments: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "recommendation_distribution": _distribution(
            assessments,
            "recommendation",
        ),
        "role_fit_distribution": _distribution(
            assessments,
            "role_fit",
        ),
        "must_have_fit_distribution": _distribution(
            assessments,
            "must_have_fit",
        ),
        "confidence_distribution": _distribution(
            assessments,
            "confidence",
        ),
        "match_score": _score_summary(assessments),
    }


def _distribution(
    assessments: list[dict[str, Any]],
    field: str,
) -> dict[str, int]:
    return dict(
        Counter(
            str(item.get(field, "unclear"))
            for item in assessments
        )
    )


def _score_summary(
    assessments: list[dict[str, Any]],
) -> dict[str, int] | None:
    scores = [
        item.get("match_score")
        for item in assessments
        if isinstance(item.get("match_score"), int)
    ]

    if not scores:
        return None

    return {
        "min": min(scores),
        "max": max(scores),
        "average": round(sum(scores) / len(scores)),
    }


def _dominant(
    assessments: list[dict[str, Any]],
    field: str,
) -> str:
    return Counter(
        str(item.get(field, "unclear"))
        for item in assessments
    ).most_common(1)[0][0]


def _fallback_summary(
    assessments: list[dict[str, Any]],
) -> str:
    recommendation = _dominant(
        assessments,
        "recommendation",
    )
    role_fit = _dominant(
        assessments,
        "role_fit",
    )
    must_have_fit = _dominant(
        assessments,
        "must_have_fit",
    )
    confidence = _dominant(
        assessments,
        "confidence",
    )

    return (
        "Match analysis produced structured prioritization evidence; "
        f"the dominant recommendation is {recommendation}, "
        f"role fit is {role_fit}, "
        f"must-have fit is {must_have_fit}, "
        f"and confidence is {confidence}."
    )


__all__ = ["summarize"]