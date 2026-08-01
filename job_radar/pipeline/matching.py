"""Transparent rule-based job matching."""

from job_radar.models.job import JobRecord
from job_radar.models.profile import MatchingRules, UserProfile


def _contains_any(text: str, keywords: list[str]) -> list[str]:
    lowered = text.lower()
    return [keyword for keyword in keywords if keyword.lower() in lowered]


def match_record(record: JobRecord, profile: UserProfile, rules: MatchingRules) -> JobRecord:
    """Score one job record and attach explainable reasons."""

    score = 0
    reasons: list[str] = []
    missing_requirements: list[str] = []
    weights = rules.weights

    target_title_hits = _contains_any(record.title, profile.target_roles or rules.title_keywords)
    rule_title_hits = _contains_any(record.title, rules.title_keywords)
    title_hits = sorted(set(target_title_hits + rule_title_hits))
    if title_hits:
        score += weights.get("title", 0)
        reasons.append(f"岗位名称匹配: {', '.join(title_hits)}")

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

    location_hits = _contains_any(record.location or "", profile.preferred_locations)
    if location_hits:
        score += weights.get("location", 0)
        reasons.append(f"地点匹配: {', '.join(location_hits)}")

    if not reasons:
        reasons.append("暂未命中当前示例画像的重点偏好")

    record.match_score = max(0, min(100, score))
    record.match_reasons = reasons
    record.missing_requirements = missing_requirements
    return record


def match_records(records: list[JobRecord], profile: UserProfile, rules: MatchingRules) -> list[JobRecord]:
    """Score a list of normalized records."""

    return [match_record(record, profile, rules) for record in records]
