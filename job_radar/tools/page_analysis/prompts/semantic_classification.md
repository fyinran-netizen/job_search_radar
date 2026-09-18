---
name: page-jd-classification
description: Classify the current acquired page before job extraction.
---

# Page Semantic Classification

Classify only the current page from the supplied `title`, `cleaned visible text`,
and `important links`. This is a semantic classification step, not acquisition
or extraction.

Never fetch, follow, open, or infer the contents of a link. A link is evidence
of the current page's structure only. Do not assume that a detail page exists,
or that it contains a particular role, until it has been acquired.

Return one JSON object with exactly the existing fields:

- `page_type`
- `suggested_next_action`
- concise `reasons`
- grounded `evidence`
- `confidence`

## Classification rules

### `job_detail`

Use only when this current page contains enough substantive JD content for
extraction: for example responsibilities, duties, qualifications, eligibility,
role-specific description, employment details, or application requirements.
A title, company, location, contact information, or apply link alone is not
enough.

`suggested_next_action` must be `extract_jobs`.

### `job_listing`

Use when the current page shows multiple independent job entries/search results
and has a clear detail-page entry/link structure. `job_detail_candidate` links,
role-specific detail labels, and consistent job/position URL paths are structural
evidence only; they do not provide the unseen detail content.

`suggested_next_action` must be `fetch_detail_links`.

### `role_list_without_jd`

Use when role names or categories are present but the current page lacks
substantive JD content and does not provide a clear detail-page entry/link
structure. Do not upgrade this to `job_listing` merely because several titles
are visible.

`suggested_next_action` must be `find_detail_pages_for_role_titles`.

### Other page types

- `recruitment_program`: program overview without enough job-level detail — `open_portal_and_find_job_detail_pages`
- `career_home`: general careers landing page — `open_portal_and_find_job_detail_pages`
- `apply_portal`: primarily application/sign-in/navigation controls — `open_portal_and_find_job_detail_pages`
- `access_or_interactive_page`: login, authorization, interactive shell, or missing rendered content — `retry_with_browser_or_rendered_collection`
- `document_or_brochure`: notice/brochure not directly extractable as a job detail — `manual_review`
- `irrelevant`: unrelated content — `skip_until_more_context`
- `uncertain`: insufficient or ambiguous evidence — `manual_review`

The `suggested_next_action` must match the page type exactly as specified above;
do not invent or freely choose another action. Keep reasons and evidence limited
to what is visible on this page. Return only JSON.
