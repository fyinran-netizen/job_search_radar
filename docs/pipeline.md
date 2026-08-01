# Job Radar Pipeline

This document is written with plain Markdown so it can be previewed without Mermaid support.

Job Radar currently has three runnable ingestion paths:

1. Demo CSV pipeline
2. Mock Agent pipeline
3. Manual URL pipeline

Both paths eventually feed the same local processing pipeline:

```text
RawJobRecord
  -> Validation
  -> Normalization
  -> Deduplication
  -> Matching
  -> SQLite
  -> Streamlit UI
```

## 1. Current Demo Pipeline

The demo path reads local sample data from `data/demo_jobs.csv`.

```text
+------------------+
| data/demo_jobs.csv |
+---------+--------+
          |
          v
+------------------+
| DemoCollector    |
+---------+--------+
          |
          v
+------------------+
| RawJobRecord     |
+---------+--------+
          |
          v
+------------------+
| Validation       |
+---------+--------+
          |
          v
+------------------+
| Normalization    |
+---------+--------+
          |
          v
+------------------+
| Deduplication    |
+---------+--------+
          |
          v
+------------------+
| Matching         |
+---------+--------+
          |
          v
+------------------+
| SQLite           |
+---------+--------+
          |
          v
+------------------+
| Streamlit UI     |
+------------------+
```

## 2. Mock Agent Pipeline

The mock agent path is the future AI-agent shape, but it does not call a real LLM and does not access the network.

It uses:

- `ProfileCompletenessChecker`
- `SearchPlanBuilder`
- `ToolScheduler`
- `MockWebSearchTool`
- `MockPageCollectorTool`
- `RuleBasedJobExtractor`
- `AgentDiscoveryCollector`

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
| SearchPlanBuilder     |
| Build SearchPlan      |
+-----------+-----------+
            |
            v
+-----------------------+
| ToolScheduler         |
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
| ToolScheduler         |
| Run mock collect_page |
+-----------+-----------+
            |
            v
+-----------------------+
| PageContent           |
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
| AgentDiscoveryCollector |
+-----------+-----------+
            |
            v
+-----------------------+
| Existing local Pipeline |
+-----------------------+
```

After `AgentDiscoveryCollector`, the data enters the same processing steps as the demo CSV pipeline.

## 3. Manual URL Pipeline

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
| HttpPageCollectorTool     |
| fetch URL with urllib     |
+-------------+-------------+
              |
              v
+---------------------------+
| PageContent               |
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

## 4. Full Target Pipeline

This is the intended long-term shape of the project.

```text
User uploads resume / fills personal information
        |
        v
AI extracts user profile
        |
        v
Profile completeness check
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
        |   Profile completeness check again
        |
        +-- Information is enough
                |
                v
        AI generates job search strategy
                |
                v
        Agent calls web_search
                |
                v
        Candidate job/source URLs
                |
                v
        Agent filters and ranks URLs
                |
                v
        collect_page fetches page content
                |
                v
        Job information extraction
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
        Job requirement understanding
                |
                v
        Match Analysis
                |
                v
        SQLite
                |
                v
        Streamlit UI
```

## 5. Step Responsibilities

| Step | Current implementation | Input | Output | Responsibility |
| --- | --- | --- | --- | --- |
| User profile | Example YAML | `profile.example.yaml` | `UserProfile` | Describe target roles, skills, company types, and locations. |
| Profile check | `ProfileCompletenessChecker` | `UserProfile` | `ProfileCompletenessResult` | Decide whether enough information exists to search. |
| Search plan | `SearchPlanBuilder` | `UserProfile` | `SearchPlan` | Generate target roles, locations, company types, and keywords. |
| Mock web search | `MockWebSearchTool` | `SearchPlan` | `CandidateSource` list | Simulate finding candidate URLs. No network requests. |
| Manual source URLs | `ManualSourceTool` | Configured sources | `CandidateSource` list | Return explicitly configured URLs for manual testing. |
| Mock page collection | `MockPageCollectorTool` | `CandidateSource` | `PageContent` | Simulate fetching page text. No network requests. |
| HTTP page collection | `HttpPageCollectorTool` | `CandidateSource` | `PageContent` | Fetch one explicitly configured URL and extract visible text and links with Python stdlib. |
| Job extraction | `RuleBasedJobExtractor` | `PageContent` | `RawJobRecord` list | Convert marker text or simple JD detail pages into raw job records. No LLM API call is made. |
| Future LLM extraction | `LLMJobExtractor` plus concrete `LLMClient` | `PageContent` | `RawJobRecord` list | Future replacement for rule-based extraction when page formats become too varied for deterministic parsing. |
| Demo collection | `DemoCollector` | `data/demo_jobs.csv` | `RawJobRecord` list | Read local demo CSV jobs. |
| Validation | `validate_records` | `RawJobRecord` list | Valid records and errors | Reject records missing required fields. |
| Normalization | `normalize_records` | Valid raw records | `JobRecord` list | Standardize company, title, location, and deduplication key. |
| Deduplication | `deduplicate_records` | `JobRecord` list | Unique jobs and duplicates | Remove obvious duplicate jobs. |
| Matching | `match_records` | Unique jobs plus profile/rules | Scored jobs | Add match score, reasons, and missing requirements. |
| Persistence | `JobRepository` | Scored jobs | SQLite rows | Insert or update by deduplication key. Preserve status and notes. |
| Service | `JobService` | Repository data | DataFrame / job list | Provide UI-ready job data and update methods. |
| UI | `app.py` | Services | Streamlit page | Show jobs, run pipelines, edit status/notes, export CSV. |

## 6. Data Shape

### RawJobRecord

`RawJobRecord` is the raw structure returned by a collector or extraction step.

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

## 7. Pipeline Result

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

## 8. Error Handling

Single bad records should not stop the whole pipeline.

Current behavior:

- Invalid records are added to `errors`.
- Invalid records increase `invalid_count`.
- Duplicate records increase `duplicate_count`.
- Persistence failures increase `failed_count`.
- Valid later records continue processing.

## 9. Current UI Buttons

### Load demo jobs

Runs:

```text
DemoCollector
-> Validation
-> Normalization
-> Deduplication
-> Matching
-> SQLite
```

### Run mock agent search

Runs:

```text
ProfileCompletenessChecker
-> SearchPlanBuilder
-> ToolScheduler
-> MockWebSearchTool
-> MockPageCollectorTool
-> RuleBasedJobExtractor
-> AgentDiscoveryCollector
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
-> HttpPageCollectorTool
-> RuleBasedJobExtractor
-> AgentDiscoveryCollector
-> Validation
-> Normalization
-> Deduplication
-> Matching
-> SQLite
```

This button proves that a manually configured real JD URL can be fetched and structured before it enters the existing local pipeline.

## 10. What Is Not Implemented Yet

The current project does not yet include:

- Real web search
- General-purpose crawling across recruitment websites
- Real LLM API calls
- Real resume parsing
- Real AI match analysis
- Real crawling of recruitment websites

Those can be added later by replacing `RuleBasedJobExtractor` with `LLMJobExtractor(real_client)` and replacing mock search tools with real search tools while keeping the local validation, normalization, deduplication, persistence, and UI layers.
