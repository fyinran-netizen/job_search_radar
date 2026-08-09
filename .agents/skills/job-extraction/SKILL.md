---
name: job-extraction
description: Extract compact semantic job data from cleaned page text. Use when Codex needs to identify company, recruitment context, dates, and per-job details while deterministic code separately preserves URLs, typed links, source provenance, and official-source status before RawJobRecord expansion.
---

# Job Extraction

## Purpose

Extract compact job data from collected page content.

Return shared recruitment semantics once in `page_context` and variable position data in `jobs`. Do not process links or source provenance; deterministic code joins those fields by `page_id` before validation.

## Input

Use only the semantic page payload:

- `page_id`
- `title`
- `visible_text`

Treat `page_id` as an opaque identifier and return it unchanged. Do not request or infer URLs, typed links, source names, company type, source-selection metadata, or official-source status.

## Output

For one input page, return one JSON object:

```json
{
  "page_id": "page-1",
  "page_context": {
    "company_name": null,
    "recruitment_type": null,
    "graduation_years": [],
    "published_at": null,
    "deadline": null
  },
  "jobs": [
    {
      "title": null,
      "location": null,
      "description": null,
      "requirements": null
    }
  ]
}
```

For multiple input pages, return a JSON array containing one such object per page.

## Extraction Rules

1. Return the input `page_id` exactly.
2. Scan the complete page for every explicitly named position or job category before constructing `jobs`.
3. Return every named position even when its location, description, or requirements are missing. Missing fields are not a reason to omit a job.
4. Treat numbered or bulleted entries under headings such as recruitment positions, open roles, or job categories as separate jobs when each entry has a distinct position name.
5. Exclude organization-only headings or generic statements that do not name a position.
6. Put fields shared by all positions on the page only in `page_context`.
7. Put `title`, `location`, `description`, and `requirements` for each distinct position in `jobs`.
8. Combine multiple locations for the same position into one location string; do not create one job per city.
9. Extract explicit candidate conditions such as graduate eligibility, degree, major, language, and skill requirements into `requirements`.
10. Preserve source wording for recruitment type and other raw text; do not translate or normalize values.
11. Return `null` for unsupported scalar fields and `[]` for missing graduation years; do not guess.
12. Keep dates in ISO 8601 format when possible.

Before returning JSON, compare `jobs` against all named positions found in the full page and add any omitted position. Do not output this coverage check.

## Constraints

- Do not output URLs, links, source names, company type, or official-source status.
- Do not repeat page-level fields inside every job.
- Do not reject jobs here; validation happens after deterministic expansion.
- Do not normalize, deduplicate, match, rank, or persist jobs.
- Do not overwrite user status or notes.
- Return only JSON when called by `ai/tasks`.
