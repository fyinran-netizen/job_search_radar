# Job Radar

Job Radar is a local job discovery, matching, and application tracking tool. The current version is phase one: it establishes a clear project architecture, a complete demo pipeline, SQLite persistence, and a minimal Streamlit interface.

This is not a complete web-wide recruitment crawler. The current focus is architecture, data pipeline behavior, and local job management.

## Current Phase

Phase one builds a working local pipeline:

```text
Data Source -> Collector -> Raw Job Records -> Validation -> Normalization
-> Deduplication -> Matching -> Persistence -> Service -> Streamlit UI
```

The demo pipeline reads `data/demo_jobs.csv`, rejects invalid records, removes obvious duplicates, scores jobs against example YAML configuration, and saves results to SQLite.

The project also includes a local mock agent pipeline. It keeps the future LLM and tool boundaries abstracted, but uses deterministic local mocks and rule-based extraction instead of a real LLM API.

There is also a manual URL pipeline for early page-structure testing. It reads explicit URLs from `config/sources.example.yaml` or private `config/sources.yaml`, fetches those pages with Python stdlib HTTP, extracts visible text, and converts simple JD detail pages into `RawJobRecord` objects before entering the existing pipeline.

## Completed Features

- Demo CSV collector with realistic sample jobs.
- Pydantic models for raw and processed job records.
- Recoverable validation errors for bad records.
- Basic company, title, and location normalization.
- Deterministic deduplication by company, title, and location.
- Explainable rule-based matching from YAML config.
- SQLite initialization and upsert persistence.
- Duplicate imports do not create duplicate rows and are reported as updates.
- User-managed status and notes are preserved on re-import.
- Streamlit UI for loading demo jobs, editing status/notes, and exporting CSV.
- Mock agent workflow with mock web search, mock page collection, extractor-based structuring, and real Pipeline persistence.
- Manual URL workflow with configured JD URLs, Python HTTP page collection, rule-based extraction, and real Pipeline persistence.
- Extractor boundary for `PageContent -> RawJobRecord`, with a rule-based implementation now and an LLM adapter ready for future API integration.
- pytest coverage for models, pipeline, repository, collector, and app import.

## Not Implemented Yet

- Real recruitment website crawling.
- Real web search or automatic URL discovery.
- General-purpose crawling across recruitment websites.
- Real LLM API calls.
- Search engine integration.
- WeChat/public account collection.
- Link verification.
- LLM parsing or matching.
- Automatic applications.
- Resume generation.
- Cloud deployment, user login, Docker, or CI/CD.

## Tech Stack

- Python 3.11+
- uv
- Streamlit
- SQLite
- pandas
- Pydantic
- PyYAML
- pytest
- pathlib

## Project Structure

```text
app.py                         Streamlit UI
config/                        Example YAML configuration
data/demo_jobs.csv             Demo job source
docs/                          Architecture and pipeline docs
job_radar/collectors/          Data collectors
job_radar/agents/              Agent workflow orchestration
job_radar/extractors/          Rule-based page-to-job extraction
job_radar/llm/                 LLM client interface and mock client
job_radar/tools/               Tool scheduler, mock tools, and manual HTTP page collector
job_radar/models/              Pydantic models
job_radar/pipeline/            Validation, normalization, deduplication, matching
job_radar/storage/             SQLite database and repository
job_radar/services/            UI-facing application services
tests/                         Automated tests
```

See `docs/project_structure.md` for more detail.

## Pipeline Overview

1. `DemoCollector` reads raw demo jobs from CSV.
2. `validate_records` checks required fields and records invalid rows.
3. `normalize_records` standardizes display fields and deduplication keys.
4. `deduplicate_records` removes obvious duplicate jobs.
5. `match_records` calculates a transparent score and reasons.
6. `JobRepository` saves jobs to `data/jobs.db` and reports inserted, updated, and failed writes.
7. `JobService` reads and updates jobs for Streamlit.

The mock agent path runs before the same local pipeline:

```text
ProfileCompletenessChecker -> SearchPlanBuilder -> ToolScheduler
-> mock web_search -> mock collect_page -> RuleBasedJobExtractor
-> Validation -> Normalization -> Deduplication -> Matching -> SQLite
```

The manual URL path also feeds the same local pipeline:

```text
ManualSourceTool -> HttpPageCollectorTool -> RuleBasedJobExtractor
-> Validation -> Normalization
-> Deduplication -> Matching -> SQLite
```

## Installation

```bash
uv sync
```

## Start The App

```bash
uv run streamlit run app.py
```

On first startup, the app initializes the local SQLite database automatically.

The UI has three ingestion buttons:

- `Load demo jobs`: reads `data/demo_jobs.csv`.
- `Run mock agent search`: runs the abstract LLM/tool workflow with local mock data.
- `Fetch manual source URL`: fetches explicitly configured JD URLs and runs the same local pipeline.

## Run Tests

```bash
uv run pytest
```

## Demo Data

`data/demo_jobs.csv` intentionally includes:

- One obvious duplicate job.
- One invalid job missing a required title.
- Official and non-official sources.
- Different company types, cities, and job directions.
- Job apply links and source links using non-real example domains.

The demo data does not contain real personal information.

## Configuration

The app looks for private config files first:

- `config/profile.yaml`
- `config/sources.yaml`
- `config/matching_rules.yaml`

If a private file is missing, the app uses the matching `.example.yaml` file and reports that in the UI. Private configs are ignored by Git.

## Privacy

The repository should not include real names, emails, phone numbers, resumes, private notes, personal configs, local databases, or real application history. Real databases and personal configuration files are excluded by `.gitignore`.

## Roadmap

- Add real company career-site collectors.
- Add CSV import for external job lists.
- Improve deduplication beyond exact normalized keys.
- Add richer matching rules and profile configuration.
- Add application timeline fields for written tests, interviews, offers, and deadlines.
- Add portfolio-oriented GitHub documentation and screenshots.
