---
name: job-understanding
description: Analyze a validated job record to produce structured semantic understanding. Use when Codex needs to identify canonical role, campus eligibility, hard requirements, nice-to-have requirements, red flags, evidence, or confidence before downstream match analysis.
---

# Job Understanding

## Purpose

Understand a validated job's semantic meaning before match analysis.

This skill identifies role category, eligibility, hard requirements, nice-to-have requirements, and risks. It should not persist anything.

## Input

- Validated `RawJobRecord` or `JobRecord`.
- Candidate profile.
- Matching rules or role taxonomy if available.

## Output

Return structured JSON with fields such as:

- `canonical_role`
- `campus_eligible`
- `hard_requirements`
- `nice_to_have`
- `red_flags`
- `evidence`
- `confidence`

## Understanding Rules

1. Identify the real role type from title, description, and requirements.
2. Determine whether the role appears suitable for the user's graduation cohort.
3. Separate hard requirements from nice-to-have requirements.
4. Flag contradictions, such as campus title but senior experience requirement.
5. Preserve evidence snippets for important conclusions.
6. Be explicit when eligibility is uncertain.

## Constraints

- Do not calculate final match score here.
- Do not discard jobs; validation and ranking decide downstream behavior.
- Do not invent requirements that are not supported by the page.
- Return only JSON when called by `ai/tasks`.
