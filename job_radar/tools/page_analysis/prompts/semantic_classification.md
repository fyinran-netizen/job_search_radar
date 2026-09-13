---
name: page-jd-classification
description: Classify a cleaned page before job extraction.
---

# Page Semantic Classification

Classify the supplied cleaned page by its current visible content only.

Do not fetch pages, follow links, infer hidden content, or perform job extraction.

## Input

- page title
- cleaned visible text
- preserved important links

## Output

Return one JSON object matching the schema with:

- `page_type`
- `suggested_next_action`
- concise `reasons`
- grounded `evidence`

## Core Rule

Use:

- `page_type: "job_detail"`
- `suggested_next_action: "extract_jobs"`

only when the supplied visible text contains enough concrete job-level content to support extraction.

A job title, company name, location, contact information, or other metadata alone is not enough.

Strong job-detail evidence includes one or more substantive sections such as:

- responsibilities / duties
- requirements / qualifications
- eligibility / graduation requirements
- role-specific description
- employment details or application requirements

If the page looks like a job detail page but the substantive JD body is missing or too incomplete for extraction, do **not** classify it as `job_detail`.

## Page Types

### `job_detail`
A concrete role or named job category with enough substantive job-level content for extraction.

Next action: `extract_jobs`

### `job_listing`
Multiple job entries or search results that lead to separate detail pages.

Next action: `fetch_detail_links`

### `role_list_without_jd`
Role titles or categories are present, but duties/requirements are not sufficiently described.

Next action: `find_detail_pages_for_role_titles`

### `recruitment_program`
Campus, graduate, internship, or early-career program overview without enough job-level detail.

Next action: `open_portal_and_find_job_detail_pages`

### `career_home`
General careers or recruitment landing page.

Next action: `open_portal_and_find_job_detail_pages`

### `apply_portal`
Primarily application, sign-in, search, or navigation controls.

Next action: `open_portal_and_find_job_detail_pages`

### `access_or_interactive_page`
Visible content clearly shows login, authorization, interactive shell, or missing rendered content.

Next action: `retry_with_browser_or_rendered_collection`

### `document_or_brochure`
Recruitment notice, brochure, or document that is not directly extractable as a job detail.

Next action: `manual_review`

### `irrelevant`
Not related to jobs or recruitment.

Next action: `skip_until_more_context`

### `uncertain`
Evidence is too sparse or ambiguous to classify reliably.

Next action: `manual_review`

## Important Rules

1. Classify only the supplied content.
2. Do not infer content that is not visible.
3. Multiple separate roles normally indicate `job_listing`.
4. Titles or metadata without substantive JD content are not `job_detail`.
5. If content is too incomplete to support extraction, prefer a non-`job_detail` label.
6. Keep reasons concise and evidence-based.
7. Return only JSON.