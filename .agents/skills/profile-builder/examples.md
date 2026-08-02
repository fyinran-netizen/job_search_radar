# Examples

## Example 1: Extract Basic Profile

Input:

```text
ANU Master student, expected to receive degree in November or December 2026.
Interested in AI application engineer, agent developer, and Python backend roles.
Skills: Python, SQL, LLM, RAG, computer vision.
Preferred cities: Shanghai, Sydney.
```

Output:

```json
{
  "education": "ANU master student",
  "graduation_date": "2026-12",
  "target_roles": ["AI Application Engineer", "Agent Developer", "Python Backend Engineer"],
  "skills": ["Python", "SQL", "LLM", "RAG", "Computer Vision"],
  "preferred_company_types": [],
  "preferred_locations": ["Shanghai", "Sydney"],
  "uncertain_fields": ["preferred_company_types"],
  "evidence": {
    "graduation_date": "User said degree expected in November or December 2026"
  },
  "confidence": 0.9
}
```
