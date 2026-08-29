---
name: match-analysis
description: Compare a validated and normalized job record against a candidate profile and explain fit with structured JSON. Use when Codex needs to produce match score, strengths, gaps, missing requirements, recommendation, explanation, or confidence without mutating application state.
---

# Match Analysis

## Purpose

Compare a job with the candidate profile and explain fit.

This skill may complement the current rule-based matcher. It should produce transparent reasons, gaps, and recommendation, not just a number.

## Input

- Candidate profile / `UserProfile`.
- Validated and normalized job record.
- Optional `JobUnderstanding`.
- Current rule-based match score and reasons, if available.

## Output

Return structured JSON with fields such as:

- `score`
- `must_have_fit`
- `preference_fit`
- `strengths`
- `gaps`
- `missing_requirements`
- `recommendation`
- `explanation`
- `confidence`

## Analysis Rules

1. Score must stay between 0 and 100.
2. Separate must-have fit from preference fit.
3. Give concrete strengths based on user skills, education, role preference, location, or company type.
4. List gaps that are actually required or strongly implied by the JD.
5. Keep explanation concise and actionable.
6. Use conservative recommendations when evidence is weak.

## Constraints

- Do not overwrite `status` or `notes`.
- Do not recommend automatic application.
- Do not claim the candidate is eligible without evidence.
- Return only JSON when called by `ai/tasks`.
