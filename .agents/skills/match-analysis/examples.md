# Examples

## Example 1: Good Fit With Gap

Input:

```json
{
  "profile": {"skills": ["Python", "LLM", "RAG"], "target_roles": ["AI Application Engineer"]},
  "job": {"title": "AI应用工程师", "requirements": "熟悉 Python，了解大模型应用开发，有部署经验优先。"}
}
```

Output:

```json
{
  "score": 82,
  "must_have_fit": 0.9,
  "preference_fit": 0.8,
  "strengths": ["Python", "LLM application interest", "RAG experience"],
  "gaps": ["production deployment experience"],
  "missing_requirements": ["deployment experience"],
  "recommendation": "优先投递",
  "explanation": "核心技能匹配，部署经验是可补充缺口。",
  "confidence": 0.84
}
```
