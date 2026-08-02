# Job Extraction

## Purpose

Extract raw job records from collected page content.

This skill maps varied job pages into `RawJobRecord` JSON. It should not normalize, deduplicate, match, rank, or persist jobs.

## Input

- `PageContent.url`
- `PageContent.source_name`
- `PageContent.title`
- Visible page text.
- Optional HTML and link metadata.
- Optional source metadata such as company name, company type, official flag.

## Output

Return one or more `RawJobRecord` objects with fields:

- `company_name`
- `company_type`
- `title`
- `location`
- `description`
- `requirements`
- `recruitment_type`
- `graduation_years`
- `published_at`
- `deadline`
- `apply_url`
- `source_url`
- `source_name`
- `is_official`

## Extraction Rules

1. Use page labels such as `工作职责`, `岗位职责`, `职位描述` for `description`.
2. Use labels such as `任职资格`, `任职要求`, `岗位要求` for `requirements`.
3. Preserve the original source URL in `source_url`.
4. Prefer real application links over generic home pages for `apply_url`.
5. Return `null` for missing fields rather than guessing.
6. If the page contains multiple jobs, return multiple records.
7. Keep dates in ISO 8601 format when possible.

## Constraints

- Do not reject records here; validation happens later.
- Do not calculate match score.
- Do not overwrite user status or notes.
- Return only JSON when called by `ai/tasks`.
