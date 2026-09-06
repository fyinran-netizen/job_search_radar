---
name: job-extraction
description: Extract explicit factual fields for the primary job on a classified job-detail page.
---

# Job Extraction

Extract at most one primary job from the supplied page. Use only the page title and visible text. Return `page_id` unchanged and output JSON only.

## Output shape

```json
{
  "page_id": "page-1",
  "page_context": {
    "company_name": null,
    "recruitment_type": null,
    "graduation_years": [],
    "graduation_start": null,
    "graduation_end": null,
    "graduation_requirement": null,
    "deadline": null,
    "education_levels": []
  },
  "jobs": [{
    "title": null,
    "locations": [],
    "description": null,
    "requirements": null
  }]
}
```

## Field definitions

- `company_name`: the original hiring organization name as shown by the source; do not normalize or infer an entity name.
- `title`: the advertised position title for the primary job.
- `locations`: every explicit work location for the primary job, as separate strings. Use an empty list when unsupported.
- `description`: explicit responsibilities, work content, or role scope.
- `requirements`: explicit candidate requirements; retain the source wording and include education, major, experience, skills, language, licenses, or eligibility when present.
- `recruitment_type`: explicit employment or recruitment context such as internship, campus recruitment, or full-time.
- `graduation_requirement`: the original wording that states a graduation/cohort eligibility condition; null when no such wording is present.
- `graduation_years`: only explicit eligible graduation years or cohorts stated in the source, represented as four-digit years.
- `graduation_start` and `graduation_end`: explicit lower and upper bounds of an eligible graduation date/window. Use ISO `YYYY-MM` or `YYYY-MM-DD` only when the source provides that precision; leave a bound null when it is not stated.
- `education_levels`: explicit education-level requirements only, using the source's clear level labels (for example, bachelor, master, doctorate, or equivalent wording). Do not infer a level from seniority, field, or general language.
- `deadline`: the final date by which an application must be submitted for this job. Do not use a publication date, start date, interview date, or an intermediate recruitment milestone.

Use `null` for unsupported scalar fields and `[]` for unsupported lists. Preserve facts exactly enough to retain their source meaning. Do not infer missing facts, classify requirement importance, match a candidate, or calculate a recommendation. Do not output URLs, provenance, company type, official-source status, or application state; those are supplied by deterministic program code. Dates must be ISO-formatted only when precision is explicit. Ignore related, recommended, sidebar, navigation, and other-job content.
