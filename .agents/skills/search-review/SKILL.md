---
name: search-review
description: Review bounded job search results and decide whether another search round is needed. Use when Codex needs a ContinueDecision-style JSON response based on current round, limits, source coverage, valid job count, duplicates, match quality, and prior queries without executing tools or mutating state.
---

# Search Review

## Purpose

Decide whether the current search results satisfy the user's goal or whether another bounded search round is needed.

This skill reviews a search round. It should not execute search and should not mutate the database.

## Input

- Candidate profile.
- Search strategy / `SearchPlan`.
- Current round number.
- Max rounds.
- Collected source count.
- Valid job count.
- Duplicate count.
- Source coverage summary.
- Match result summary.
- Previous queries and rejected sources if available.

## Output

Return `ContinueDecision`-style JSON with fields:

- `continue_search`
- `reason`
- `adjustments`
- `next_round_priority`

`adjustments` may include:

- `add_queries`
- `add_sources`
- `add_roles`
- `exclude`

## Decision Rules

1. If valid job count reaches `target_valid_jobs`, usually stop.
2. If quantity is enough but quality is low, continuing may be reasonable.
3. If an important source type is missing, suggest a focused follow-up search.
4. Never exceed `max_rounds`.
5. Do not repeat exactly the same query.
6. Adjustments must be incremental; do not overturn the original strategy without a clear reason.
7. If uncertain, write the uncertainty into `reason`.

## Constraints

- Do not keep irrelevant jobs just to satisfy quantity.
- Do not bypass program limits.
- Do not trigger automatic application.
- Return only JSON when called by `ai/tasks`.
