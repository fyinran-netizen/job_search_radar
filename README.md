# Job Radar

Job Radar is a local job discovery, matching, and application tracking tool. The current version is phase one: it establishes a clear project architecture, a complete demo pipeline, SQLite persistence, and a minimal Streamlit interface.

This is not a complete web-wide recruitment crawler. The current focus is architecture, data pipeline behavior, and local job management.

The long-term direction is the agent workflow in `docs/job_search_agent_full_flow.svg`: program-controlled orchestration, structured AI decisions, bounded tool execution, deterministic validation, and local persistence. The SVG is a planning aid; this README is the source of truth for what is implemented today.

## Current Phase

Phase one builds a working local pipeline:

```text
Data Source -> Tool/Extractor -> Raw Job Records -> Validation -> Normalization
-> Deduplication -> Matching -> Persistence -> Service -> Streamlit UI
```

The demo pipeline reads `data/demo_jobs.csv`, rejects invalid records, removes obvious duplicates, scores jobs against example YAML configuration, and saves results to SQLite.

The project also includes a local agent-shaped pipeline. The first runnable version is intentionally chain-based rather than a fully dynamic graph: Python owns the order of operations, AI returns bounded structured outputs, and tools execute through `ToolExecutor`.

The current chain is:

```text
UserProfile
-> Python required-field completeness check
-> AI or deterministic SearchPlan generation
-> web_search
-> collect_page
-> Python hard-failure PageFilter
-> AIPageInput trimming
-> future AI job extraction
-> Pydantic validation
-> normalization / deduplication / matching / persistence
```

This is still agent-oriented because the project already separates AI decisions, tool execution, deterministic guardrails, and run state. It is not yet a free-form agent that lets AI choose arbitrary tools.

There is also a manual URL pipeline for early page-structure testing. It reads explicit URLs from `config/sources.example.yaml` or private `config/sources.yaml`, fetches those pages with Python stdlib HTTP, extracts visible text, and converts simple JD detail pages into `RawJobRecord` objects before entering the existing pipeline.

Profile completeness is intentionally checked by deterministic Python rules. Future AI profile extraction can populate candidate fields from resumes or user notes, but code decides whether required fields are present before search strategy generation.

When the Streamlit app runs the mock agent search, it tries to generate the search plan through the local Codex CLI if `codex` is installed and logged in on the user's machine. That uses the active user's own Codex account. If Codex is unavailable or fails to return valid JSON, Job Radar falls back to the deterministic local search-plan builder.

For command-line experiments, the project also has a Codex-backed `web_search` tool adapter. It is designed so a cloned project can use the current user's local Codex login and quota. If Codex is unavailable, mock data remains available for demos and tests.

## Completed Features

- Demo CSV tool with realistic sample jobs.
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
- Deterministic profile completeness gate for required fields such as target roles, skills, and graduation year/date.
- Optional Codex CLI-backed search strategy generation with deterministic fallback.
- Codex CLI-backed `web_search` CLI slice for generating `CandidateSource` URLs from a static `SearchPlan`.
- Python HTTP page collection and hard-failure page filtering before AI extraction.
- `AIPageInput` trimming so AI job extraction receives only `url`, `final_url`, `title`, and cleaned visible text instead of search-stage metadata.
- Extractor boundary for `PageContent -> RawJobRecord`, with a rule-based implementation now and an LLM adapter ready for future API integration.
- pytest coverage for models, pipeline, repository, tools, agent flow, and app import.

## Not Implemented Yet

- Real recruitment website crawling.
- Fully integrated real web search inside the Streamlit pipeline.
- General-purpose crawling across recruitment websites.
- Real LLM API calls outside local Codex CLI experiments.
- Search engine integration outside the Codex-backed CLI adapter.
- WeChat/public account collection.
- Full link verification and job-closed detection.
- LLM parsing or matching in the main Streamlit pipeline.
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
job_radar/agent/               Workflow orchestration, state, guardrails, limits
job_radar/ai/                  Skill loading, prompts, AI tasks, Codex CLI provider
job_radar/extractors/          PageContent to RawJobRecord extraction boundary
job_radar/tools/               ToolExecutor and deterministic function tools
job_radar/models/              Pydantic models
job_radar/pipeline/            Validation, normalization, deduplication, matching
job_radar/storage/             SQLite database and repository
job_radar/services/            UI-facing application services
tests/                         Automated tests
```

See `docs/project_structure.md` for more detail.

## Pipeline Overview

The current runnable pipeline is the deterministic core of the future agent workflow.

1. `DemoCsvTool` reads raw demo jobs from CSV.
2. `validate_records` checks required fields and records invalid rows.
3. `normalize_records` standardizes display fields and deduplication keys.
4. `deduplicate_records` removes obvious duplicate jobs.
5. `match_records` calculates a transparent score and reasons.
6. `JobRepository` saves jobs to `data/jobs.db` and reports inserted, updated, and failed writes.
7. `JobService` reads and updates jobs for Streamlit.

The mock agent path runs before the same local pipeline:

```text
ProfileCompletenessChecker -> AutoSearchPlanBuilder/SearchPlanBuilder -> ToolExecutor
-> mock web_search -> mock collect_page -> RuleBasedJobExtractor
-> Validation -> Normalization -> Deduplication -> Matching -> SQLite
```

The experimental real-search CLI path is:

```text
SearchPlan JSON
-> Codex-backed web_search
-> CandidateSource[] JSON
-> HttpPageTool collect_page
-> PageFilter hard-failure screening
-> AIPageInput trimming
```

The page filter is deliberately conservative. It rejects only obvious hard failures such as fetch errors, bad HTTP status codes, explicit error redirects, 404/not found pages, closed jobs, ended recruitment, or obvious login walls. It does not reject short pages, listing pages, or pages that merely lack obvious JD keywords; those are left for AI extraction and later validation.

Before AI job extraction, `AIPageInput` removes search-stage fields such as `relevance_score`, source-selection `reason`, `company_type`, `is_official`, and link metadata. This reduces token usage and avoids biasing the extractor with earlier AI guesses.

## Agentic Upgrade Path

The current design can grow into a more agentic workflow without replacing the chain. The intended progression is:

1. Keep the single-round chain fixed until search, page collection, extraction, validation, and persistence work end to end.
2. Add real AI job extraction behind `LLMJobExtractor` using the existing `AIPageInput` boundary.
3. Add run logging for `SearchPlan`, `CandidateSource`, page-filter decisions, token usage, and tool events.
4. Add a narrow `search-review` / `ContinueDecision` step after one full round.
5. Let AI propose the next bounded search round only after Python validates max rounds, budgets, privacy rules, duplicate queries, and allowed tools.
6. Add AI `ToolPlan` later, only when there are multiple real search tools worth choosing between.

The agent boundary is therefore:

```text
AI proposes structured decisions.
Python validates decisions and controls the workflow.
ToolExecutor executes only allowed tools.
Pipeline code validates, normalizes, deduplicates, persists, and protects user state.
```

The manual URL path also feeds the same local pipeline:

```text
ManualSourceTool -> HttpPageTool -> RuleBasedJobExtractor
-> Validation -> Normalization
-> Deduplication -> Matching -> SQLite
```

## Installation

On Windows, use the project-local uv wrapper to keep uv cache, uv-managed Python installs, and temp files under `.local_tmp/` instead of the user profile on `C:`.

```powershell
.\scripts\uv-local.ps1 sync
```

If an older `.venv` points to a missing uv-managed Python under the user profile, rebuild it inside the project:

```powershell
.\scripts\uv-local.ps1 sync --python 3.13.13 --reinstall
```

On other systems, either set the same environment variables or run uv directly:

```bash
UV_CACHE_DIR=.local_tmp/uv-cache UV_PYTHON_INSTALL_DIR=.local_tmp/uv-python uv sync
```

## Start The App

```powershell
.\scripts\uv-local.ps1 run streamlit run app.py
```

On first startup, the app initializes the local SQLite database automatically.

The UI has three ingestion buttons:

- `Load demo jobs`: reads `data/demo_jobs.csv`.
- `Run mock agent search`: generates a search plan with local Codex CLI when available, then runs the abstract tool workflow with local mock search/page data.
- `Fetch manual source URL`: fetches explicitly configured JD URLs and runs the same local pipeline.

## CLI Experiments

Generate a search strategy:

```powershell
.\scripts\uv-local.ps1 run python -m job_radar.cli.search_strategy --provider codex --show-meta
```

Run web search from a static plan:

```powershell
.\scripts\uv-local.ps1 run python -m job_radar.cli.web_search --provider codex --plan-file .test_tmp/search_plan_example.json --max-sources 5
```

Collect pages and run hard-failure filtering:

```powershell
.\scripts\uv-local.ps1 run python -m job_radar.cli.collect_pages --sources-file .test_tmp/candidate_sources_example.json --plan-file .test_tmp/search_plan_example.json --timeout-seconds 15 --snippet-chars 500 --output-run-dir .test_tmp/page_runs
```

The terminal output is a compact filter report. `--output-run-dir` overwrites `accepted_pages.json`, `pending_pages.json`, and `page_collection_report.json` in the given artifact directory. The report includes `collected_at` so the current files still record when they were refreshed.

Clean accepted pages into AI extraction inputs:

```powershell
.\scripts\uv-local.ps1 run python -m job_radar.cli.clean_pages --pages-file .test_tmp/page_runs/accepted_pages.json --output-file .test_tmp/page_runs/cleaned_pages.json --report-file .test_tmp/page_runs/page_cleaning_report.json --max-text-chars 12000
```

`cleaned_pages.json` contains `AIPageInput[]` records with cleaned text plus deterministic provenance: source URLs, source metadata, official-source status, and typed links such as attachments or apply links. Only `page_id`, `title`, and `visible_text` are sent to the AI extraction prompt. The program injects provenance and links into extracted records after the semantic response, so the model cannot rewrite them. The original accepted page artifact remains available for audit and retries.

Extract jobs from cleaned pages, then validate, normalize, and deduplicate them without matching or persistence:

```powershell
.\scripts\uv-local.ps1 run python -m job_radar.cli.extract_jobs --cleaned-pages-file .test_tmp/page_runs/cleaned_pages.json --output-run-dir .test_tmp/page_runs
```

By default this uses the local Ollama HTTP API with `qwen3.5:cloud`, so the project does not store an API key. Run `ollama signin` and `ollama pull qwen3.5:cloud` first for Ollama cloud models. Override with `--ollama-model` or `--provider codex` if needed.

This writes only `prepared_jobs.json`. Duplicate records, invalid records, and the extraction report are printed to the terminal. `prepared_jobs.json` is the structured, validated, normalized, deduplicated job artifact intended for later `job-understanding` and match analysis.

## Run Tests

```powershell
.\scripts\uv-local.ps1 run pytest
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

- Add real company career-site tools.
- Add CSV import for external job lists.
- Improve deduplication beyond exact normalized keys.
- Add richer matching rules and profile configuration.
- Add application timeline fields for written tests, interviews, offers, and deadlines.
- Add portfolio-oriented GitHub documentation and screenshots.
