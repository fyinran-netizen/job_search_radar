# Job Radar

Job Radar is a local-first job discovery, matching, and application-tracking tool. The current release is an agent v1 architecture and end-to-end demonstration, not a general-purpose recruitment crawler.

The application keeps workflow control, AI decisions, tool execution, deterministic processing, and user state separate:

```text
Profile -> Agent Controller -> ToolExecutor -> Page/Job Tools
       -> Validation -> Normalization -> Deduplication -> Matching
       -> SQLite Repository -> Streamlit UI
```

## Current capabilities

- Streamlit profile form and persisted job table with editable status and notes.
- Bounded agent loop with validated `AgentState`, explicit `AgentLimits`, action transitions, and decision tracing.
- Deterministic `RuleBasedController` for the current baseline, with a validated controller boundary reserved for future structured decisions.
- Deterministic profile completeness checks before search planning.
- Mock web search and mock page acquisition for network-free development and tests.
- Optional Tavily web search and Python HTTP page acquisition for explicitly configured real searches.
- Page handling in two stages: acquisition performs fetch/recovery, then analysis performs cleaning, quality checks, and semantic classification.
- Structured job extraction, job understanding, and match analysis tools with Pydantic validation and deterministic fallbacks.
- Recoverable handling for invalid records, rejected pages, and pending follow-ups; one bad item does not fail the whole run.
- SQLite persistence with duplicate protection and preservation of user-managed status and notes.
- Local runtime/cache paths under `.local_tmp/` when using the provided uv wrapper.

The mock path must remain deterministic and must not call a real LLM API or make network requests. Real collection is opt-in through configured tools and providers. Automatic broad crawling, Playwright automation, login flows, and automated applications are outside the current scope.

## Architecture

### Agent layer

`job_radar/agent/` owns the bounded workflow contract:

- `models.py`: validated run state, limits, errors, and run results.
- `actions.py`: allowed action names and state transitions.
- `controllers/`: controller interface plus rule-based and LLM controller implementations.
- `guardrails.py` and `limits.py`: source selection and run bounds.

### Tools and processing

`job_radar/tools/` contains callable capabilities registered with `ToolExecutor`:

- `web_search/`: search plans, source selection, mock provider, and optional Tavily provider.
- `page_acquisition/`: mock, HTTP, browser fallback, JS-shell detection, embedded JSON recovery, and acquisition triage.
- `page_analysis/`: content cleaning, quality checks, and semantic classification; it never accesses the network.
- `job_extraction/`: raw/job models, extraction, validation, normalization, and quality checks.
- `job_understanding/`: structured job requirement analysis.
- `match_analysis/`: basic gates, deterministic scoring, and optional semantic matching.

Every tool call goes through `ToolExecutor`, which restricts calls to registered tools and records a compact execution trace.

### Infrastructure and application boundaries

- `job_radar/profile/`: profile models, normalization, construction, and completeness checks.
- `job_radar/infra/llm/`: Ollama, prompt loading, and structured output validation.
- `job_radar/infra/http/`: HTTP client support.
- `job_radar/infra/storage/`: SQLite initialization and repository methods.
- `job_radar/infra/paths.py`: project-relative config and data paths.
- `job_radar/services/`: application use cases, including the bounded agent service and ingestion orchestration.
- `job_radar/frontend/`: Streamlit presentation and UI-facing view/service helpers.
- `job_radar/cli/`: command-line entry points for individual pipeline stages.

## Agent v1 flow

The current controller-driven flow is:

```text
Profile completeness gate
-> SearchPlan
-> web_search
-> bounded source selection
-> acquire_page
-> page acquisition and recovery
-> page analysis: cleaning, quality checks, semantic classification
-> semantic page routing
-> job extraction
-> job understanding
-> match analysis
-> persistence
```

Each stage updates validated state. Limits such as maximum rounds, sources per round, relevance threshold, and retained results are enforced in Python. AI-backed components return structured Pydantic models; deterministic components remain the default for tests and mock execution.

## Project layout

```text
app.py                    Streamlit entry point
config/                   Example YAML configuration
docs/                     Architecture and pipeline documentation
job_radar/agent/          Agent state, actions, controllers, and guardrails
job_radar/frontend/       Streamlit UI and view models
job_radar/infra/          HTTP, LLM, logging, paths, runtime, and SQLite
job_radar/profile/        User profile models and completeness checks
job_radar/services/       Application-level orchestration
job_radar/tools/          Registered search, acquisition, analysis, and extraction tools
tests/                    Unit, integration, smoke, fixtures, and test doubles
```

## Installation

Python 3.11+ and [uv](https://docs.astral.sh/uv/) are required. On Windows, the project wrapper keeps uv-managed files and temporary runtime artifacts inside the repository:

```powershell
.\scripts\uv-local.ps1 sync
```

On other systems:

```bash
uv sync
```

Private configuration is read from these files when present, otherwise the corresponding examples are used:

- `config/profile.yaml`
- `config/sources.yaml`
- root `.env` for provider settings

Copy and edit the example files locally as needed. They are intentionally excluded from Git when they contain personal data or credentials.

## Run the app

```powershell
.\scripts\uv-local.ps1 run streamlit run app.py
```

The app initializes `data/jobs.db` on first use. The profile form runs the bounded agent service. The testing tools use mock providers and are intended for local development checks.

## CLI pipeline

The CLI commands can be run independently against JSON artifacts in a temporary directory:

```powershell
.\scripts\uv-local.ps1 run python -m job_radar.cli.web_search --provider mock --plan-file .test_tmp/search_plan.json --max-sources 5
.\scripts\uv-local.ps1 run python -m job_radar.cli.acquire_pages --sources-file .test_tmp/candidate_sources.json --output-run-dir .test_tmp/page_run
.\scripts\uv-local.ps1 run python -m job_radar.cli.clean_pages --pages-file .test_tmp/page_run/readable_pages.json --output-file .test_tmp/page_run/cleaned_pages.json
.\scripts\uv-local.ps1 run python -m job_radar.cli.classify_pages --cleaned-pages-file .test_tmp/page_run/cleaned_pages.json --output-jd-cleaned-pages-file .test_tmp/page_run/jd_cleaned_pages.json
.\scripts\uv-local.ps1 run python -m job_radar.cli.extract_jobs --cleaned-pages-file .test_tmp/page_run/jd_cleaned_pages.json --output-run-dir .test_tmp/page_run
.\scripts\uv-local.ps1 run python -m job_radar.cli.understand_jobs --prepared-jobs-file .test_tmp/page_run/prepared_jobs.json --output-file .test_tmp/page_run/job_understandings.json
.\scripts\uv-local.ps1 run python -m job_radar.cli.analyze_matches --job-understandings-file .test_tmp/page_run/job_understandings.json --prepared-jobs-file .test_tmp/page_run/prepared_jobs.json --output-file .test_tmp/page_run/match_assessments.json
```

Provider-backed commands require the relevant local configuration. The mock provider and fixtures are the supported network-free path.

## Tests

```powershell
.\scripts\uv-local.ps1 run pytest
```

The suite covers models, tools, processing, pipeline behavior, repository persistence, agent actions/controllers/services, and Streamlit import smoke checks.

## Scope and roadmap

Current work focuses on a safe, observable single-round agent slice. Future work can add richer orchestrator decisions, explicit run logging, iterative search review, real LLM extraction, stronger deduplication, link/job-closure verification, and additional career-site tools after their limits and privacy rules are defined.

The project does not currently provide automatic applications, resume generation, cloud deployment, authentication, or unrestricted crawling.

## Privacy

Do not commit real names, email addresses, phone numbers, resumes, private notes, personal configuration, local databases, logs containing personal data, or application history. Use the example configuration and test fixtures for reproducible development.
