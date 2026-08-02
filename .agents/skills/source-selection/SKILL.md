# Source Selection

## Purpose

Select candidate URLs worth fetching from search results.

This skill should prefer pages likely to contain a concrete job description. It should not fetch the page itself.

## Input

- Search strategy or search query.
- Raw search results with title, URL, snippet, source name, and fetched time.
- Optional previous accepted/rejected URLs.

## Output

Return a list of `CandidateSource`-compatible JSON objects:

- `url`
- `title`
- `source_name`
- `company_name`
- `company_type`
- `is_official`
- `relevance_score`
- `reason`

## Selection Rules

1. Prefer concrete job detail pages with title, company, location, description, requirements, and application entry.
2. Prefer official company career pages when available.
3. Third-party pages are acceptable when they expose a real job description and application/source link.
4. Avoid generic landing pages, login-only pages, forum discussions, SEO pages, and duplicate URLs.
5. Assign higher `relevance_score` to pages matching the target role, graduation cohort, and location.
6. Explain why each selected URL is worth fetching.

## Constraints

- Do not fetch URLs.
- Do not select pages for automatic application.
- Do not include URLs that appear unsafe or unrelated.
- Return only JSON when called by `ai/tasks`.
