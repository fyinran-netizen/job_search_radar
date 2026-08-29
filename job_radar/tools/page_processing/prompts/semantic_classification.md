---
name: page-jd-classification
description: Classify a technically processed page by semantic page type before job extraction.
---

# Page Semantic Classification

Technical insufficiency is not itself a semantic page type. Use
`access_or_interactive_page` only when the supplied cleaned content clearly
shows a login, portal, or interactive shell. If the content is merely too
short or otherwise insufficient to determine the page type, use `uncertain`.

## Purpose

Classify a page after deterministic technical processing, recovery, and cleaning have already been completed.

This task decides only:

1. the semantic type of the current page; and
2. a bounded routing hint for the next program or Agent action.

It does not:

- fetch or open new pages;
- follow links;
- extract job records;
- perform technical fetch/readability checks;
- perform deterministic content recovery;
- infer hidden content;
- rank sources;
- compare the page with a candidate profile;
- decide candidate-job fit.

The supplied page represents the best content currently available from deterministic page processing.

## Input

- Page title.
- Cleaned visible text.
- Important links preserved by deterministic code.
- Allowed page type labels and next-action labels from the schema.

## Output

Return one JSON object matching the supplied schema.

The classification must describe only the current supplied page.

Use:

- `page_type: "job_detail"`
- `suggested_next_action: "extract_jobs"`

only when the supplied visible text contains enough concrete job-level information for job extraction.

For useful pages that are not directly extractable job details, return the most specific non-`job_detail` type and a bounded next-action hint.

## Page Types

### `job_detail`

Use when the current page clearly describes a concrete role, internship, graduate-program stream, or named job category and contains enough job-specific information for extraction.

Useful evidence may include:

- responsibilities;
- requirements;
- qualifications;
- eligibility;
- graduation requirements;
- location;
- employment type;
- application details;
- role-specific description.

A page does not need every field above, but it must contain meaningful job-level content rather than only a role title or navigation entry.

Suggested next action:

`extract_jobs`

### `job_listing`

Use when the current page contains multiple job entries, search results, or a list of roles that lead to separate detail pages.

Do not extract or follow those entries in this task.

Suggested next action:

`fetch_detail_links`

### `role_list_without_jd`

Use when the page contains recognizable role titles or categories but does not contain enough duties, requirements, or job-specific detail for extraction.

Suggested next action:

`find_detail_pages_for_role_titles`

### `apply_portal`

Use when the page primarily provides application, sign-in, search, or navigation controls rather than job-description content.

Suggested next action:

`open_portal_and_find_job_detail_pages`

### `recruitment_program`

Use for broad campus, graduate, internship, or early-careers program overview pages that describe a hiring program but do not provide enough job-level detail for direct extraction.

Suggested next action:

`open_portal_and_find_job_detail_pages`

### `career_home`

Use for company-wide career hubs or general recruitment landing pages.

Suggested next action:

`open_portal_and_find_job_detail_pages`

### `document_or_brochure`

Use for recruitment brochures, notices, document-like pages, or PDFs that are not directly extractable job-detail pages.

Suggested next action:

`manual_review`

### `access_or_interactive_page`

Use only when the current supplied content, after deterministic recovery has already been attempted, still represents an interactive shell, login/authorization page, or page whose useful job content is unavailable without further browser interaction or rendered collection.

Do not infer what hidden content may exist.

Suggested next action:

`retry_with_browser_or_rendered_collection`

### `irrelevant`

Use when the current page is unrelated to jobs or recruitment.

Suggested next action:

`skip_until_more_context`

### `uncertain`

Use when the supplied evidence is too sparse, generic, or ambiguous to assign a more specific semantic type.

Suggested next action:

`manual_review`

## Classification Rules

1. Classify only the current supplied page.
2. Use only the supplied title, cleaned visible text, and important-link labels as evidence.
3. Do not assume linked pages have been visited.
4. Do not assume browser-rendered, hidden, or dynamically loaded content exists unless it is present in the supplied input.
5. Do not perform technical recovery reasoning. Technical routing and deterministic recovery have already happened before this task.
6. `job_detail` requires concrete job-level content, not merely recruitment relevance.
7. Multiple jobs or search results should normally be `job_listing`.
8. Role names without sufficient JD content should normally be `role_list_without_jd`.
9. Broad graduate or campus hiring descriptions should normally be `recruitment_program`, unless the current page itself contains extractable job-level detail.
10. A portal, landing page, or career hub should not be promoted to `job_detail` merely because job-related keywords appear.
11. `suggested_next_action` is only a routing hint. Do not execute the action.
12. Keep reasons concise and grounded in the supplied content.
13. Evidence should quote or paraphrase specific supplied signals rather than speculate.
14. Lower confidence when the supplied content is sparse, generic, or ambiguous.

## Constraints

- Do not extract job records.
- Do not follow links.
- Do not fetch additional pages.
- Do not perform browser interaction.
- Do not classify source trustworthiness.
- Do not compare against the candidate profile.
- Do not reject pages for technical reasons.
- Do not infer hidden or unavailable content.
- Return only JSON when invoked by the runtime task.
