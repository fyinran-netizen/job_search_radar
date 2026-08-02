# Examples

## Example 1: Incomplete Profile

Input:

```json
{
  "education": "ANU master student",
  "graduation_date": "2026-12",
  "target_roles": [],
  "skills": ["Python", "SQL"],
  "preferred_locations": []
}
```

Output:

```json
{
  "is_complete": false,
  "missing_fields": ["target_roles"],
  "questions": ["What target roles should Job Radar search for? For example: AI application engineer, data analyst, or Python backend engineer."]
}
```

## Example 2: Sufficient Profile

Input:

```json
{
  "education": "ANU master student",
  "graduation_date": "2026-12",
  "target_roles": ["AI Application Engineer"],
  "skills": ["Python", "LLM", "RAG"],
  "preferred_locations": ["Shanghai", "Sydney"]
}
```

Output:

```json
{
  "is_complete": true,
  "missing_fields": [],
  "questions": []
}
```
