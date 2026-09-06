---
name: job-understanding
description: Structure job responsibilities and candidate requirements for downstream matching.
---

# Job Understanding

## Purpose

Convert the supplied job text into structured semantic facts for downstream matching.

Focus on:
- what the role does
- what the employer expects from a candidate

## Input

- title
- description
- requirements
- recruitment_type, when available

## Output

Return one JSON object matching the supplied `JobRequirementFacts` schema.

## Rules

1. Derive `canonical_role`, `role_family`, and `seniority` only from the supplied job text.
2. Split responsibilities into distinct items.
3. Split candidate requirements into distinct semantic items and assign each a coarse category.
4. Preserve the original meaning and explicit wording, including preference or priority language.
5. Avoid restating simple factual information that adds no useful semantic value for downstream matching.
6. Use `work_context` only for meaningful role or working-context information.
7. Use `risk_flags` only for material ambiguity, contradiction, or internal inconsistency in the job text.
8. Preserve the source language.
9. Do not invent or strengthen unsupported facts.

## Constraints

- Do not compare against the candidate.
- Do not score or recommend.
- Return only valid JSON.