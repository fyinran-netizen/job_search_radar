# Examples

## Example 1: Prefer JD Detail Page

Input:

```json
{
  "query": "2027届 AI软件工程师 校招",
  "results": [
    {"title": "Company Campus Recruitment", "url": "https://example.com/campus", "snippet": "Campus home page"},
    {"title": "AI软件工程师（2027校园招聘）", "url": "https://example.com/zpdetail/123", "snippet": "工作职责 任职资格 工作地点"}
  ]
}
```

Output:

```json
[
  {
    "url": "https://example.com/zpdetail/123",
    "title": "AI软件工程师（2027校园招聘）",
    "source_name": "example.com",
    "company_name": null,
    "company_type": null,
    "is_official": true,
    "relevance_score": 92,
    "reason": "Concrete job detail page with responsibilities, requirements, and location."
  }
]
```
