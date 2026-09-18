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
2. Base all judgments on explicit evidence from the supplied candidate profile and job understanding.
3. Use the job understanding as the primary representation of the role, responsibilities, and candidate requirements.
4. Evaluate role alignment from the overall direction of the role and the candidate's stated target direction, not from isolated transferable skills.
5. Evaluate each candidate requirement against relevant candidate evidence and keep positive and missing judgments mutually consistent.
6. Treat absence of evidence as missing support, not as proof that the candidate lacks the capability.
7. Use `risk_flags` only for material ambiguity or uncertainty in the semantic comparison.
8. Keep `match_reasons` concise, evidence-based, and non-redundant.
9. Preserve uncertainty where the available evidence is insufficient; do not infer or strengthen unsupported facts.

## Constraints

- Do not calculate a match score or recommendation.
- Do not make deterministic eligibility, deadline, graduation, or location decisions.
- Do not reinterpret or override program-owned facts.
- Do not modify application `status` or `notes`.
- Return only valid JSON matching the supplied schema.