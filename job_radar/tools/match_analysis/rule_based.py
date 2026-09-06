"""Transparent rule-based job matching."""

from job_radar.tools.job_extraction.models import JobRecord
from job_radar.profile.models import UserProfile
from job_radar.tools.match_analysis.models import MatchingRules
from job_radar.tools.match_analysis.models import FinalMatchAssessment


def _contains_any(text: str, keywords: list[str]) -> list[str]:
    lowered = text.lower()
    return [keyword for keyword in keywords if keyword.lower() in lowered]


def match_record(record: JobRecord, profile: UserProfile, rules: MatchingRules) -> FinalMatchAssessment:
    """Score one prepared job and return a separate match artifact."""

    score = 0
    reasons: list[str] = []
    missing_requirements: list[str] = []
    weights = rules.weights

    target_title_hits = _contains_any(record.title, profile.target_roles or rules.title_keywords)
    rule_title_hits = _contains_any(record.title, rules.title_keywords)
    title_hits = sorted(set(target_title_hits + rule_title_hits))
    if title_hits:
        score += weights.get("title", 0)
        reasons.append(f"职位标题匹配: {', '.join(title_hits)}")

    job_text = " ".join([record.description or "", record.requirements or ""])
    skill_hits = _contains_any(job_text, profile.skills)
    if skill_hits:
        max_skill_score = weights.get("skill", 0)
        score += min(max_skill_score, len(skill_hits) * max(1, max_skill_score // 3))
        reasons.append(f"技能匹配: {', '.join(skill_hits)}")

    required_skill_hits = _contains_any(job_text, rules.skill_keywords)
    missing_requirements = sorted(
        {skill for skill in required_skill_hits if skill.lower() not in {item.lower() for item in profile.skills}}
    )

    if record.company_type and record.company_type in profile.preferred_company_types:
        score += weights.get("company_type", 0)
        reasons.append(f"公司类型匹配: {record.company_type}")

    location_hits = _contains_any(", ".join(record.locations), profile.preferred_locations)
    if location_hits:
        score += weights.get("location", 0)
        reasons.append(f"地点匹配: {', '.join(location_hits)}")

    if not reasons:
        reasons.append("暂未命中当前示例匹配规则")

    final_score = max(0, min(100, score))
    return FinalMatchAssessment(
        match_score=final_score,
        role_fit="high" if final_score >= 70 else "medium" if final_score >= 40 else "low",
        must_have_fit="partial" if missing_requirements else "yes",
        match_reasons=reasons,
        missing_requirements=missing_requirements,
        risk_flags=[],
        job_summary=f"{record.company_name} - {record.title}",
        recommendation="apply" if final_score >= 70 else "consider" if final_score >= 40 else "low_priority",
        confidence="medium",
        analysis_source="deterministic",
        deterministic_reasons=[],
    )


def match_records(records: list[JobRecord], profile: UserProfile, rules: MatchingRules) -> list[FinalMatchAssessment]:
    """Score a list of prepared records into separate match artifacts."""

    return [match_record(record, profile, rules) for record in records]


