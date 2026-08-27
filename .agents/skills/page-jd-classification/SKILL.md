---
name: page-jd-classification
description: Classify readable page text by semantic page type before extraction.
---

# Page Semantic Classification

## Purpose

Classify a collected and cleaned readable page before job extraction.

This task decides only the semantic page type and the next bounded program action. It does not extract jobs, judge technical fetch/readability failures, rank sources, infer hidden content, or decide candidate fit.

## Input

- Page title.
- Cleaned visible text.
- Important links preserved by deterministic code.
- Allowed page type labels and next-action labels from the schema.

## Output

Return one JSON object matching the supplied schema.

Use `page_type: "job_detail"` and `suggested_next_action: "extract_jobs"` only when the visible text itself contains a concrete role, internship, graduate program stream, or named job category with enough job-description content to support extraction.

For all other useful but unresolved pages, return the most specific non-`job_detail` page type with `suggested_next_action`, reasons, evidence, and confidence.

## Classification Rules

1. Classify `job_detail` only when the visible text clearly describes a concrete role, internship, graduate program stream, or named job category and includes job-specific duties, requirements, qualifications, eligibility, location, or application details.
2. Classify pages that list multiple jobs or search results as `job_listing`.
3. Classify pages focused on sign-in, application forms, or apply/search controls rather than JD text as `apply_portal`.
4. Classify broad campus, graduate, internship, or early-careers program overview pages as `recruitment_program` unless they contain extractable job-level detail.
5. Classify company-wide career hubs as `career_home`.
6. Classify pages with role names but no concrete duties or requirements as `role_list_without_jd`.
7. Classify brochures, PDFs, notices, and document-like pages as `document_or_brochure` when they are not extractable job details.
8. Classify pages that require interaction, login, rendering, or navigation before job content is visible as `access_or_interactive_page`.
9. Classify pages unrelated to jobs or recruitment as `irrelevant`.
10. Use `uncertain` when the evidence is too ambiguous for a more specific label.
11. Use the visible text as the evidence source. Do not assume hidden, rendered, linked, or browser-visible content exists when it is not present in the supplied text.
12. Use `suggested_next_action` to describe the next bounded program action, not a final decision. Use `fetch_detail_links` for listings, `open_portal_and_find_job_detail_pages` for portals, `retry_with_browser_or_rendered_collection` for interactive/rendered content, `manual_review` for uncertainty, and `skip_until_more_context` for irrelevant pages.
13. Keep reasons concise and grounded in the supplied title, visible text, or important link labels.
14. Set confidence lower when the text is sparse, generic, or ambiguous.

## Constraints

- Do not extract job records.
- Do not classify source trustworthiness.
- Do not compare the page to the candidate profile.
- Do not reject pages for technical reasons; Stage 1 program routing has already handled technical rejection and recovery.
- Return only JSON when called by `ai/tasks`.
