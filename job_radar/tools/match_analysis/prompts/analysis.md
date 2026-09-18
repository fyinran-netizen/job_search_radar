---
name: match-analysis
description: Compare a candidate profile with one understood job and return semantic role and requirement fit as structured JSON.
---

# Match Analysis

## Purpose

Compare one candidate with one understood job and return only semantic judgments that require contextual reasoning.

## Input

- Candidate profile / `UserProfile`.
- Normalized job fields.
- Candidate-independent job understanding.

## Output

Return one JSON object matching the supplied semantic match schema.

## Analysis Rules

1. Judge only role alignment and candidate requirement fit.
2. Use only explicit evidence from the candidate profile, including stated target roles, skills, education, and experience.
3. Use the supplied job understanding as the primary source of candidate requirements.
4. Do not turn job responsibilities into candidate requirements.
5. List `missing_requirements` only when a represented candidate requirement lacks supporting candidate evidence.
6. Use `risk_flags` only for material semantic uncertainty or ambiguous evidence in the comparison.
7. Keep `match_reasons` concise and evidence-based.
8. Preserve uncertainty rather than guessing or strengthening unsupported evidence.

## Constraints

- Do not calculate a match score or recommendation.
- Do not make deterministic eligibility, deadline, graduation, or location decisions.
- Do not reinterpret or override program-owned facts.
- Do not modify application `status` or `notes`.
- Return only valid JSON matching the supplied schema.