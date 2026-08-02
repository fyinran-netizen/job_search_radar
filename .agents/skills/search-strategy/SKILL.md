# Search Strategy

## Purpose

Generate a bounded job search strategy from a complete candidate profile.

This skill creates search intent and query candidates. It does not execute tools and does not fetch pages.

## Input

- Candidate profile / `UserProfile`.
- Matching rules or target role keywords.
- Current round number and previous queries if available.
- App limits such as max rounds and target valid job count.

## Output

Return a `SearchPlan`-compatible JSON object:

- `target_roles`
- `locations`
- `company_types`
- `keywords`

Future versions may also include:

- `exclude_keywords`
- `source_priorities`
- `target_valid_jobs`
- `max_rounds`
- `stop_conditions`

## Strategy Rules

1. Convert target roles into search keywords, not full paragraphs.
2. Include graduation cohort terms such as `2027届`, `2027 graduate`, `campus recruitment`, or `Graduate Program` when relevant.
3. Include location terms only when the profile or user goal requires them.
4. Include company type terms such as bank, state-owned enterprise, foreign company, or technology company when preferred.
5. Avoid queries that imply senior-only or social recruitment roles unless the user asked for them.
6. Do not repeat exactly the same query from previous rounds.

## Constraints

- Do not execute web search.
- Do not include private user information in queries.
- Do not exceed configured query count or round limits.
- Return only JSON when called by `ai/tasks`.
