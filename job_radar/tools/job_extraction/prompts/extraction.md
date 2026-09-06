---
name: job-extraction
description: Extract the primary job and its recruitment context from a page already classified as a job-detail page.
---

# Job Extraction

## Purpose

Extract structured data for the primary job represented by the current page.

The page has already been classified as `job_detail`, so return at most one job.

Use semantic understanding of the page as a whole. The page title, main job heading, and main JD content are the strongest evidence. Ignore surrounding content that does not belong to the primary job.

## Input

Use only:

- `page_id`
- `title`
- `visible_text`

Return `page_id` unchanged.

## Output

{
  "page_id": "page-1",
  "page_context": {
    "company_name": null,
    "recruitment_type": null,
    "graduation_years": [],
    "graduation_start": null,
    "graduation_end": null,
    "graduation_requirement": null,
    "start_date": null,
    "start_date_text": null,
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

For multiple input pages, return a JSON array containing one such object per page.

Return at most one item in `jobs` for each page.

## Extraction Principles

- Extract only facts that belong to the primary job.
- Use the page title, main job heading, and main JD content as the strongest evidence for identifying the primary role.
- `company_name` means the actual hiring organization for the primary job. Distinguish it from recruiting agencies, job platforms, unrelated organizations, and interface or navigation text.
- If the employer identity or any other field is ambiguous, undisclosed, or unsupported by the page, return `null` rather than guessing.
- Extract only information that semantically belongs to the primary job. Ignore surrounding content that belongs to other roles or general page structure.
- Keep job responsibilities, candidate requirements, recruitment context, graduation eligibility, dates, and locations semantically distinct.
- Preserve explicit source meaning and do not infer unsupported facts.
- Return at most one primary job for each page.

## Field Semantics

- `title`: the primary advertised position.
- `location`: the location or locations of the primary job.
- `description`: the responsibilities, work content, or scope of the primary job.
- `requirements`: explicit candidate requirements such as education, major, experience, technical skills, language, or eligibility.
- `company_name`: the actual hiring organization when clearly supported by the page.
- `recruitment_type`: the explicitly stated recruitment or employment type.
- `graduation_years`: explicit candidate graduation eligibility years only.
- `graduation_start` and `graduation_end`: explicit graduation eligibility date bounds.
- `graduation_requirement`: source wording describing graduation eligibility.
- `start_date` and `start_date_text`: explicit role, internship, onboarding, joining, or program start timing.
- `published_at`: explicit publication date of the job or recruitment notice.
- `deadline`: explicit application closing date or deadline.

Use ISO 8601 date formats when the source provides enough precision.

Return `null` for unsupported scalar fields and `[]` for missing graduation years.

## Constraints

- Do not output URLs, links, source names, company type, official-source status, or other provenance fields handled deterministically outside this task.
- Do not reject jobs here. Validation happens after deterministic expansion.
- Do not normalize, deduplicate, rank, match, validate, or persist jobs.
- Do not overwrite user status or notes.
- Return JSON only when called by `ai/tasks`.