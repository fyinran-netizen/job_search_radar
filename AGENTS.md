# Job Radar Development Guide

## Project Purpose

Job Radar is a local-first job discovery, matching, and application-tracking tool.

The program controls workflow and state. AI components return structured decisions, tools perform bounded external actions, and deterministic Python code validates outputs before execution or persistence.

## Architecture Rules

* Profile completeness is checked by deterministic Python code.
* AI decisions must use Pydantic-validated structured outputs.
* Controllers decide the next action but must not directly perform tool work or mutate persistent state.
* External actions must go through `ToolExecutor`.
* Validate actions before execution and validate tool or AI outputs before persistence.
* Preserve source URLs throughout collection, extraction, and storage.
* Invalid individual records must be reported without failing the entire run.
* Keep deterministic fallbacks for AI-backed behavior.
* Tests and mock workflows must not access the network or call real LLM APIs.

## Module Responsibilities

* `agent/`: agent state, controllers, actions, limits, planning, and orchestration.
* `ai/tasks/`: job-search-specific AI decisions and deterministic fallbacks.
* `ai/providers/`: model/provider adapters without business logic.
* `tools/`: bounded external capabilities and tool execution.
* `extractors/`: conversion of page content into structured job records.
* `pipeline/`: validation, normalization, deduplication, and matching.
* `storage/`: SQLite schema and parameterized repository operations.
* `services/`: application use cases used by the UI.
* `app.py`: Streamlit presentation only; no direct SQL or provider logic.

## External Access

* Keep search, page collection, and model calls explicitly configured.
* Enforce round, result, and budget limits before adding iterative behavior.
* Do not add automated job applications, login automation, or broad unrestricted crawling.
* Dynamic-page collection must remain bounded and callable through the tool layer.

## Code Style

* Use Python type annotations and `pathlib`.
* Use Pydantic models for structured boundaries.
* Use parameterized SQL.
* Keep modules small and purposeful.
* Avoid empty placeholder abstractions.
* Store dates as ISO 8601 strings.

## Privacy

Never commit real names, email addresses, phone numbers, resumes, private notes, personal configuration, local databases, credentials, or real application history.

## Verification

Run the full test suite after changes:

```bash
uv run pytest
```

For Streamlit startup checks:

```bash
uv run streamlit run app.py
```

Architecture details and the long-term workflow belong in `docs/`, including `docs/job_search_agent_full_flow.svg`.
