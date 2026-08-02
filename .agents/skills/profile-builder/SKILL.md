# Profile Builder

## Purpose

Extract a privacy-safe candidate profile from resume text, user notes, and explicit preferences.

This skill prepares the profile data that later search, matching, and review steps use. It should not decide whether to search or which tools to call.

## Input

- Resume text extracted by program tools.
- User-written personal summary or preferences.
- Optional existing `UserProfile` fields from `config/profile.yaml` or `profile.example.yaml`.
- Optional source metadata such as file name and extraction time.

## Output

Return a JSON object compatible with the current `UserProfile` contract plus optional diagnostic fields for future models:

- `education`
- `graduation_date`
- `target_roles`
- `skills`
- `preferred_company_types`
- `preferred_locations`
- `uncertain_fields`
- `evidence`
- `confidence`

## Extraction Rules

1. Prefer explicit user-provided information over inferred information.
2. Preserve dates in ISO-like format when possible, for example `2026-12` or `2026-12-01`.
3. Normalize skills to concise keywords such as `Python`, `SQL`, `LLM`, `Computer Vision`.
4. Keep target roles as role names, not full search queries.
5. Put uncertain or inferred values into `uncertain_fields` and explain uncertainty in `evidence`.
6. Do not include private contact details such as real name, phone, email, address, student ID, or resume file path.

## Constraints

- Return only JSON when called by `ai/tasks`.
- Do not invent education, graduation date, skills, or preferences.
- Do not decide profile completeness here; use `profile-completeness` for that.
- Do not generate search queries here; use `search-strategy` for that.
