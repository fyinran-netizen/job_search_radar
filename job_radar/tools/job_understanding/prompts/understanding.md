---
name: job-understanding
description: Analyze a validated job record to produce structured, discipline-neutral requirement facts after deterministic gates and before semantic matching.
---

# Job Understanding

## Purpose

Understand a prepared job's role meaning and requirements before match analysis.

This task converts title, description, requirements, and explicit job metadata into structured facts. It does not score the candidate, rank the job, mutate state, or decide final eligibility.

## Input

* A validated, normalized, deduplicated prepared job record.
* Explicit job metadata contained in the prepared job record.
* Program basic gate output as read-only context for already-known deterministic facts.

## Output

Return one JSON object matching the supplied `JobRequirementFacts` schema.

The output should be useful for every discipline, not only technical roles. A software role may include programming languages. A policy, marketing, finance, legal, education, design, operations, or research role may instead emphasize writing, analysis, stakeholder communication, domain knowledge, accreditation, portfolio, language ability, location, availability, or other discipline-specific requirements.

## Understanding Rules

1. Identify the real role in `canonical_role`, using the title, description, requirements, and explicit job metadata without adding unsupported specialization.
2. Use consistent lowercase `role_family` labels such as technology, finance, policy, marketing, operations, legal, education, design, research, consulting, healthcare, engineering, administration, sales, customer support, or unclear.
3. Use `seniority` only when supported by evidence: internship, graduate, entry_level, experienced, leadership, or unclear. Preserve unclear rather than inferring seniority from weak contextual signals.
4. Extract responsibilities separately from candidate requirements, and do not treat company descriptions, team introductions, benefits, or recruitment slogans as responsibilities.
5. Put requirements in `hard_requirements` only when the full sentence or surrounding context makes the item a necessary candidate condition. Section titles, recruiting language, and generic role expectations are not enough by themselves.
6. Put advantages, preferences, nice-to-have capabilities, broad success traits, and uncertain requirements in `preferred_requirements` or `work_context`, according to their meaning. Preserve uncertainty rather than upgrading ambiguous text into a hard requirement.
7. Put explicit and objectively checkable graduation year, cohort, work authorization, location, availability, language, degree, major, license, certification, portfolio, or minimum experience conditions in `eligibility_constraints`. Do not duplicate these facts in `hard_requirements` or `preferred_requirements`, and do not treat general job metadata as a candidate eligibility condition without supporting evidence.
8. Keep each `RequirementFact.importance` consistent with its array: `hard_requirements` use `hard`, `preferred_requirements` use `preferred`, and `eligibility_constraints` use `hard` only for explicit eligibility gates otherwise `unclear`.
9. Use only categories allowed by the output schema. Do not use output array names such as `hard_requirements`, `preferred_requirements`, `eligibility_constraints`, or `work_context` as requirement categories.
10. Use the most fitting requirement category. Do not force non-technical requirements into `technical_skill`, and keep general personal attributes separate from objectively checkable eligibility conditions.
11. Preserve short, direct evidence snippets for important conclusions. Evidence must contain the supporting text or explicit metadata value rather than only a field name, and missing or null information must not be used to support a positive conclusion.
12. Use `risk_flags` only for uncertainty, inconsistency, or missing information within the job record itself. Do not include candidate mismatch, user preference, match quality, basic-gate decisions, or program-owned source provenance in these flags.
13. Set confidence according to the completeness, specificity, consistency, and directness of the available evidence. Lower confidence when the job text is sparse, generic, contradictory, ambiguous, or mostly inferred from metadata.

## Constraints

* Do not calculate match score.
* Do not recommend apply/skip.
* Do not compare the candidate's skills, qualifications, or preferences to the job's requirements.
* Do not use candidate profile information to produce job facts or risk flags.
* Do not reinterpret or override the program basic gate output.
* Do not invent requirements that are not supported by the page or explicit job metadata.
* Do not infer positive facts from missing, null, generic, or unrelated contextual metadata.
* Keep `hard_requirements`, `preferred_requirements`, and `eligibility_constraints` semantically consistent and non-duplicative.
* Do not discard jobs; the program-owned gates decide downstream handling.
* Return only JSON when called by `ai/tasks`.
