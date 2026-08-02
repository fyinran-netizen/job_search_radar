---
name: profile-completeness
description: Decide whether a candidate profile has enough information for a useful job search. Use when Codex needs to produce ProfileCompletenessResult-compatible JSON with completeness status, missing fields, and concise user-facing questions without starting search or fabricating data.
---

# Profile Completeness

## Purpose

Decide whether the candidate profile has enough information to run a useful job search.

This skill should judge search usefulness, not merely whether every possible field is filled.

## Input

- Candidate profile or current `UserProfile`.
- Current app requirements.
- Optional user goal for this search round.

## Output

Return a `ProfileCompletenessResult`-compatible JSON object:

- `is_complete`
- `missing_fields`
- `questions`

Future Codex-backed versions may also include:

- `ambiguities`
- `reason`
- `confidence`

## Decision Rules

1. `target_roles`, `skills`, and `graduation_date` are usually critical for meaningful search.
2. `preferred_locations` is critical when the user cares about city or country scope.
3. `preferred_company_types` is useful but not always blocking.
4. Ask only questions that materially improve search quality.
5. If the user is eligible for multiple graduation cohorts, ask a clarifying question rather than guessing.
6. Prefer concise, user-facing questions.

## Constraints

- Do not fabricate missing fields.
- Do not start search when critical fields are missing.
- Do not ask for private identifiers such as real name, phone, email, or address.
- Return only JSON when called by `ai/tasks`.
