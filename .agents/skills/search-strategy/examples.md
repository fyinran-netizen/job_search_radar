# Examples

## Example 1: 2027 AI Application Search

Input:

```json
{
  "profile": {
    "graduation_date": "2026-12",
    "target_roles": ["AI Application Engineer", "Agent Developer"],
    "skills": ["Python", "LLM", "RAG"],
    "preferred_locations": ["Shanghai", "Suzhou"],
    "preferred_company_types": ["Technology", "Bank"]
  }
}
```

Output:

```json
{
  "target_roles": ["AI Application Engineer", "Agent Developer"],
  "locations": ["Shanghai", "Suzhou"],
  "company_types": ["Technology", "Bank"],
  "keywords": [
    "2027届 AI应用工程师 校招 上海",
    "2027届 Agent 开发 校招 苏州",
    "2027 graduate AI application engineer China",
    "银行 科技岗 2027届 校园招聘 AI"
  ]
}
```
