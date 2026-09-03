# Job Radar Pipeline

This document is written with plain Markdown so it can be previewed without Mermaid support.

`docs/job_search_agent_full_flow.svg` is the target workflow. This document explains how the current runnable pipeline maps to that target.

Job Radar currently has three runnable ingestion paths:

1. Mock Agent pipeline
2. Manual URL pipeline
3. Real search pipeline

All current ingestion paths eventually feed the same deterministic local processing pipeline:

```text
RawJobRecord
  -> Validation
  -> Normalization
  -> Deduplication
  -> Matching
  -> SQLite
  -> Streamlit UI
```

## 1. Mock Agent Pipeline

The mock agent path is the future AI-agent shape. In tests and default service construction it does not call a real LLM and does not access the network. In the Streamlit app, it may use the active user's local Codex CLI login to generate only the `SearchPlan`; mock search and mock page acquisition still do not make real web requests.

It uses:

- `ProfileCompletenessChecker`
- `BuildSearchPlanTool` / deterministic `SearchPlanBuilder`
- `ToolExecutor`
- `MockWebSearchTool`
- `MockPageTool`
- `RuleBasedJobExtractor`
- `JobDiscoveryAgent`

```text
+-----------------------+
| UserProfile YAML      |
+-----------+-----------+
            |
            v
+-----------------------+
| ProfileCompleteness   |
| Check profile         |
+-----------+-----------+
            |
            v
+-----------------------+
| build_search_plan     |
| SearchPlanBuilder      |
| Build SearchPlan      |
+-----------+-----------+
            |
            v
+-----------------------+
| ToolExecutor          |
| Run mock web_search   |
+-----------+-----------+
            |
            v
+-----------------------+
| CandidateSource URLs  |
+-----------+-----------+
            |
            v
+-----------------------+
| ToolExecutor          |
| Run mock acquire_page |
+-----------+-----------+
            |
            v
+-----------------------+
| PageDocument           |
+-----------+-----------+
            |
            v
+-----------------------+
| RuleBasedJobExtractor |
| Extract jobs          |
+-----------+-----------+
            |
            v
+-----------------------+
| JobDiscoveryAgent       |
+-----------+-----------+
            |
            v
+-----------------------+
| Existing local Pipeline |
+-----------------------+
```

After `JobDiscoveryAgent`, the extracted raw records enter the same deterministic local processing pipeline.

## 2. Manual URL Pipeline

The manual URL path uses the same agent/tool shape, but replaces mock search results with URLs configured in `config/sources.example.yaml` or private `config/sources.yaml`.

For the current experiment, the enabled example source is:

```text
https://kedacom.zhiye.com/zpdetail/511158941
```

This path does make a direct Python HTTP request to the explicitly configured URL. It still does not use search APIs, Playwright, browser automation, or an LLM API.

```text
+---------------------------+
| config/sources.example.yaml |
+-------------+-------------+
              |
              v
+---------------------------+
| ManualSourceTool          |
| returns CandidateSource   |
+-------------+-------------+
              |
              v
+---------------------------+
| HttpPageTool     |
| fetch URL with urllib     |
+-------------+-------------+
              |
              v
+---------------------------+
| PageDocument               |
| html, visible text, links |
+-------------+-------------+
              |
              v
+---------------------------+
| RuleBasedJobExtractor     |
| creates RawJobRecord      |
+-------------+-------------+
              |
              v
+---------------------------+
| Existing local Pipeline   |
+---------------------------+
```

This lets the project test the real page-fetching and backend structuring boundary before connecting web search or LLM APIs.

## 3. Real Search Pipeline

The real search path is the current end-to-end experiment. It uses Codex CLI for bounded web search, Python HTTP collection, deterministic technical page routing, AI semantic page routing, AI extraction, deterministic job preparation, AI job understanding, and AI/rule-based match analysis.

```text
UserProfile
-> SearchPlan
-> CodexWebSearchTool
-> CandidateSource[]
-> HttpPageTool
-> PageFilterTool
-> PageCleaningTool
-> PageClassificationTool
-> JobExtractionTool
-> Validation / Normalization / Deduplication
-> JobUnderstandingTool
-> MatchAnalysisTool
-> SQLite
```

This path is still bounded and controller-driven. AI returns structured decisions; program code validates schemas, applies limits, executes tools, and persists accepted results.

## 4. Full Target Pipeline

This is the intended long-term shape of the project and should stay aligned with `docs/job_search_agent_full_flow.svg`.

```text
User uploads resume / fills personal information
        |
        v
Program checks file and extracts raw text
        |
        v
AI returns CandidateProfile JSON
        |
        v
Program validates and merges profile
        |
        v
Python profile completeness check
        |
        +-- Missing required information
        |       |
        |       v
        |   AI tells user what is missing
        |       |
        |       v
        |   User adds information
        |       |
        |       v
        |   Python profile completeness check again
        |
        +-- Information is enough
                |
                v
        AI returns SearchStrategy JSON
                |
                v
        Program validates constraints
                |
                v
        AI returns ToolPlan JSON
                |
                v
        Program executes approved tools
                |
                v
        RawSearchResult / CandidateSource URLs
                |
                v
        Program filters and ranks URLs
                |
                v
        acquire_page fetches page content
                |
                v
        JobExtractor creates RawJobRecord
                |
                v
        Validation
                |
                v
        Normalization
                |
                v
        Deduplication
                |
                v
        AI returns JobUnderstanding JSON
                |
                v
        AI/rules return MatchAssessment JSON
                |
                v
        AI returns ContinueDecision JSON
                |
                +-- continue within limits
                |       |
                |       v
                |   update SearchStrategy and run next round
                |
                +-- stop / enough / over limit
                |
                v
        SQLite
                |
                v
        Streamlit UI
```

## 5. SVG Alignment Principles

The target SVG uses a strict division of responsibility:

| Responsibility | Owner | Why |
| --- | --- | --- |
| Workflow control | Program / Orchestrator | Prevents AI from skipping validation, persistence rules, budgets, or privacy boundaries. |
| Ambiguous understanding | AI | Resume interpretation, search strategy, varied JD extraction, requirement understanding, and match explanation need semantic judgment. |
| External action | Tools | Web search, URL fetch, file parsing, browser/site adapters, and future APIs should be explicit tool calls. |
| Data quality | Pydantic + pipeline code | Every AI/tool output must pass schema validation, normalization, deduplication, and persistence rules. |
| User state | SQLite repository | Status, notes, favorites, and application history must not be overwritten by re-imports or AI output. |

This is why the current project should avoid growing page-specific parsing rules indefinitely. `RuleBasedJobExtractor` is useful as a mock/fallback, but varied pages should eventually go through `LLMJobExtractor` plus Pydantic validation.

## 6. Current Step Responsibilities

| Step | Current implementation | Input | Output | Responsibility |
| --- | --- | --- | --- | --- |
| User profile | Example YAML | `profile.example.yaml` | `UserProfile` | Describe target roles, skills, company types, and locations. |
| Profile check | `ProfileCompletenessChecker` | `UserProfile` | `ProfileCompletenessResult` | Deterministically check required fields before search. |
| Search plan | `BuildSearchPlanTool` / `SearchPlanBuilder` | `SearchStrategyContext` | `SearchPlan` | Generate bounded role-led queries from profile and cross-round history using deterministic Python rules. |
| Mock web search | `MockWebSearchTool` | `SearchPlan` | `CandidateSource` list | Simulate finding candidate URLs. No network requests. |
| Manual source URLs | `ManualSourceTool` | Configured sources | `CandidateSource` list | Return explicitly configured URLs for manual testing. |
| Mock page acquisition | `MockPageTool` | `CandidateSource` | `PageDocument` | Simulate fetching page text. No network requests. |
| HTTP page acquisition | `HttpPageTool` | `CandidateSource` | `PageDocument` | Fetch one explicitly configured URL, detect JS shells, recover embedded content, and use the browser fallback when required. |
| Page analysis | `PageAnalysisTool` | `PageDocument` | cleaned/classified pages and quality outcomes | Clean acquired content, run quality checks, and perform semantic classification. It does not access the network or recover pages. |
| Semantic page routing | `PageSemanticClassifier` / `PageClassificationTool` | `AIPageInput` | job-detail pages and pending follow-ups | AI-owned Stage 2 routing for page types such as job detail, listing, portal, recruitment program, career home, and irrelevant. |
| Job extraction | `RuleBasedJobExtractor` | `PageDocument` | `RawJobRecord` list | Convert marker text or simple JD detail pages into raw job records. No LLM API call is made. |
| Future LLM extraction | `LLMJobExtractor` plus concrete `LLMClient` | `PageDocument` | `RawJobRecord` list | Future replacement for rule-based extraction when page formats become too varied for deterministic parsing. |
| Validation | `validate_records` | `RawJobRecord` list | Valid records and errors | Reject records missing required fields. |
| Normalization | `normalize_records` | Valid raw records | `JobRecord` list | Standardize company, title, location, and deduplication key. |
| Deduplication | `deduplicate_records` | `JobRecord` list | Unique jobs and duplicates | Remove obvious duplicate jobs. |
| Matching | `match_records` | Unique jobs plus profile/rules | Scored jobs | Add match score, reasons, and missing requirements. |
| Persistence | `JobRepository` | Scored jobs | SQLite rows | Insert or update by deduplication key. Preserve status and notes. |
| Service | `JobService` | Repository data | DataFrame / job list | Provide UI-ready job data and update methods. |
| UI | `app.py` | Services | Streamlit page | Show jobs, run pipelines, edit status/notes, export CSV. |

## 7. Future Structured AI Decisions

The SVG implies several AI return types. These should become Pydantic models before real LLM calls are added:

| Decision model | Purpose | Must be validated before use |
| --- | --- | --- |
| `CandidateProfileDecision` | Extract education, graduation date, skills, projects, preferences, uncertain fields. | Required fields, date format, confidence, no private data leakage. |
| `SearchStrategy` | Generate role groups, queries, source priorities, exclusions, target count, max rounds. | Query length, allowed sources, target limits, privacy rules. |
| `ToolPlan` | Choose tools and call order for one search round. | Tool names, args schema, domains, rate/budget limits. |
| `JobUnderstanding` | Understand role type, campus eligibility, hard requirements, risks. | Valid role taxonomy, confidence, source evidence. |
| `MatchAssessment` | Score fit, gaps, recommendation, explanation. | Score range, required reasons, no unsupported claims. |
| `ContinueDecision` | Decide whether another search round is needed. | Round limit, target count, source coverage, budget. |

The current code already has models for `UserProfile`, `SearchPlan`, `CandidateSource`, `PageDocument`, `RawJobRecord`, and `JobRecord`. The future models above should be added around those existing models, not replace them.

## 8. Migration Path Toward The SVG

The recommended migration order is:

1. Add an `orchestrator/` layer that owns run state, round limits, and the fixed workflow.
2. Add Pydantic models for `CandidateProfileDecision`, `SearchStrategy`, `ToolPlan`, `JobUnderstanding`, `MatchAssessment`, and `ContinueDecision`.
3. Add a validated future SearchPlanBuilder implementation behind the shared Protocol when AI planning is explicitly introduced.
4. Replace `ManualSourceTool` / `MockWebSearchTool` with a real search tool behind the same `ToolExecutor`.
5. Replace most rule-based page extraction with `LLMJobExtractor`, while keeping `RuleBasedJobExtractor` for mock pages and fallback.
6. Add AI-backed job understanding and match assessment after normalization/deduplication.
7. Persist run logs, decision JSON, tool events, and user feedback so later rounds can improve search.

The existing validation, normalization, deduplication, repository, and Streamlit status/notes behavior should remain stable during this migration.

## 9. Data Shape

### RawJobRecord

`RawJobRecord` is the raw structure returned by a tool or extraction step.

It contains source-facing fields such as:

- `company_name`
- `company_type`
- `title`
- `location`
- `description`
- `requirements`
- `recruitment_type`
- `graduation_years`
- `published_at`
- `deadline`
- `apply_url`
- `source_url`
- `source_name`
- `is_official`

### JobRecord

`JobRecord` is the cleaned and persistable structure.

It keeps the raw fields and adds:

- `normalized_company_name`
- `normalized_title`
- `normalized_location`
- `deduplication_key`
- `match_score`
- `match_reasons`
- `missing_requirements`
- `status`
- `notes`
- `first_seen_at`
- `last_seen_at`
- `created_at`
- `updated_at`

## 10. Pipeline Result

Each pipeline run returns a `PipelineResult`.

```text
collected_count
valid_count
invalid_count
duplicate_count
inserted_count
updated_count
failed_count
errors
```

Meaning:

| Field | Meaning |
| --- | --- |
| `collected_count` | Number of raw records collected or extracted. |
| `valid_count` | Number of records that passed validation. |
| `invalid_count` | Number of rejected records. |
| `duplicate_count` | Number of duplicate records removed from the current batch. |
| `inserted_count` | Number of new jobs inserted into SQLite. |
| `updated_count` | Number of existing jobs updated in SQLite. |
| `failed_count` | Number of records that failed during persistence. |
| `errors` | Validation or persistence errors that did not stop the whole run. |

## 11. Error Handling

Single bad records should not stop the whole pipeline.

Current behavior:

- Invalid records are added to `errors`.
- Invalid records increase `invalid_count`.
- Duplicate records increase `duplicate_count`.
- Persistence failures increase `failed_count`.
- Valid later records continue processing.

## 12. Current UI Actions

### Run mock agent search

Runs:

```text
ProfileCompletenessChecker
-> build_search_plan/SearchPlanBuilder
-> ToolExecutor
-> MockWebSearchTool
-> MockPageTool
-> RuleBasedJobExtractor
-> Validation
-> Normalization
-> Deduplication
-> Matching
-> SQLite
```

This button proves the agent/tool orchestration works locally, but it does not perform real web search.

### Fetch manual source URL

Runs:

```text
ManualSourceTool
-> HttpPageTool
-> RuleBasedJobExtractor
-> Validation
-> Normalization
-> Deduplication
-> Matching
-> SQLite
```

This button proves that a manually configured real JD URL can be fetched and structured before it enters the existing local pipeline.

## 13. What Is Not Implemented Yet

The current project does not yet include:

- Real web search
- General-purpose crawling across recruitment websites
- Real LLM API calls
- Real resume parsing
- Real AI match analysis
- Real crawling of recruitment websites
- Orchestrator run state and iterative search rounds
- Structured AI decision models from the SVG

Those can be added later by replacing `RuleBasedJobExtractor` with `LLMJobExtractor(real_client)` and replacing mock search tools with real search tools while keeping the local validation, normalization, deduplication, persistence, and UI layers.
