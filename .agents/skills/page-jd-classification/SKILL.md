---
name: page-jd-classification
description: Decide whether collected page text is clearly a concrete job detail page before extraction.
---

# Page JD Classification

## Purpose

Classify a collected and cleaned page before job extraction.

This task decides only whether the supplied page text is clearly a concrete job detail page. It does not extract jobs, reject pages, rank sources, infer missing content, or decide candidate fit.

## Input

- Page title.
- Cleaned visible text.
- Important links preserved by deterministic code.

## Output

Return one JSON object matching the supplied schema.

Use `is_job_detail_page: true` only when the visible text itself contains a concrete role or program detail with enough job-description content to support extraction.

For all other useful but unresolved pages, return `is_job_detail_page: false` with a `pending_kind`, `suggested_next_action`, reasons, evidence, and confidence.

## Classification Rules

1. Mark a page as a job detail page only when the visible text clearly describes a concrete role, internship, graduate program stream, or named job category and includes job-specific duties, requirements, qualifications, eligibility, location, or application details.
2. Treat portal pages, search pages, broad early-careers pages, company career hubs, application landing pages, sparse notices, role lists without descriptions, and pages whose visible text lacks the actual job content as pending rather than accepted.
3. Use the visible text as the evidence source. Do not assume hidden, rendered, linked, or browser-visible content exists when it is not present in the supplied text.
4. Choose the most fitting pending kind from the schema. Prefer `official_apply_portal` for apply or career portals, `job_listing_page` for pages that list links or search results, `role_list_without_jd` for role names without concrete duties or requirements, `javascript_rendered_or_hidden_content` when the text suggests missing rendered content, `campus_brochure_or_notice` for broad recruitment notices, and `not_job_detail_page` when none of the specific categories fits.
5. Use `suggested_next_action` to describe the next bounded program action, not a final decision. Use detail-link actions for portals and listings, rendered collection for missing rendered content, and manual review for uncertain pages.
6. Keep reasons concise and grounded in the supplied title, visible text, or important link labels.
7. Set confidence lower when the text is sparse, generic, or ambiguous.

## Constraints

- Do not extract job records.
- Do not classify source trustworthiness.
- Do not compare the page to the candidate profile.
- Do not reject pages; non-JD pages remain pending for a later bounded follow-up.
- Return only JSON when called by `ai/tasks`.
