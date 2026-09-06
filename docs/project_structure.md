# Project Structure

```text
job_search_radar/
|-- .agents/
|   `-- skills/
|       |-- profile-builder/
|       |-- job-extraction/
|       |-- job-understanding/
|       |-- match-analysis/
|       `-- search-review/
|-- app.py
|-- .gitignore
|-- pyproject.toml
|-- uv.lock
|-- README.md
|-- AGENTS.md
|-- config/
|   |-- profile.example.yaml
|   |-- sources.example.yaml
|   `-- matching_rules.example.yaml
|-- data/
|   `-- .gitkeep
|-- docs/
|   |-- architecture.md
|   |-- pipeline.md
|   |-- project_structure.md
|   `-- job_search_agent_full_flow.svg
|-- job_radar/
|   |-- __init__.py
|   |-- config.py
|   |-- agent/
|   |   |-- __init__.py
|   |   |-- orchestrator.py
|   |   |-- state.py
|   |   |-- transitions.py
|   |   |-- guardrails.py
|   |   `-- limits.py
|   |-- ai/
|   |   |-- __init__.py
|   |   |-- skill_loader.py
|   |   |-- prompt_builder.py
|   |   |-- structured_output.py
|   |   |-- providers/
|   |   |   |-- __init__.py
|   |   |   |-- base.py
|   |   |   `-- mock.py
|   |   `-- tasks/
|   |       |-- __init__.py
|   |       `-- search_strategy.py
|   |-- extractors/
|   |   |-- __init__.py
|   |   |-- base.py
|   |   |-- llm.py
|   |   `-- rule_based.py
|   |-- models/
|   |   |-- __init__.py
|   |   |-- decisions.py
|   |   |-- job.py
|   |   |-- profile.py
|   |   |-- run.py
|   |   |-- search.py
|   |   `-- tool.py
|   |-- pipeline/
|   |   |-- __init__.py
|   |   |-- validation.py
|   |   |-- normalization.py
|   |   |-- deduplication.py
|   |   |-- matching.py
|   |   `-- runner.py
|   |-- profile/
|   |   |-- __init__.py
|   |   `-- completeness.py
|   |-- services/
|   |   |-- __init__.py
|   |   |-- ingestion_service.py
|   |   `-- job_service.py
|   |-- storage/
|   |   |-- __init__.py
|   |   |-- database.py
|   |   `-- repository.py
|   |-- tools/
|   |   |-- __init__.py
|   |   |-- base.py
|   |   |-- executor.py
|   |   |-- factory.py
|   |   `-- functions/
|   |       |-- __init__.py
|   |       |-- http_page.py
|   |       |-- job_semantics.py
|   |       |-- manual_sources.py
|   |       |-- mock_page.py
|   |       |-- page_analysis.py
|   |       `-- mock_web_search.py
|   `-- utils/
|       |-- __init__.py
|       |-- logging.py
|       `-- paths.py
`-- tests/
    |-- conftest.py
    |-- test_agent_tools.py
    |-- test_app_smoke.py
    |-- test_models.py
    |-- test_pipeline.py
    `-- test_repository.py
```

## Responsibility Boundaries

Runtime prompt assets live with their owning tools under `job_radar/tools/*/prompts/`. They define the task instructions and expected JSON shape, not business logic.

`job_radar/tools/search_plan/` contains the deterministic `build_search_plan` Agent Tool and shared `SearchPlanBuilderProtocol`. Future optional builders can implement the Protocol without changing the tool or provider boundaries.

`job_radar/profile/` contains deterministic profile checks. Profile completeness is a Python required-field gate, not an AI decision.

`job_radar/infra/llm/` contains the low-level Ollama provider, structured-output validation, and runtime prompt helpers. It must not contain job-search business rules.

`job_radar/agent/` owns workflow control: orchestration, state, transitions, limits, and guardrails. It decides when to call tasks, tools, and extractors, but it does not fetch pages directly or write to storage.

`job_radar/tools/` contains executable actions. Page acquisition owns manual source loading, mock/HTTP/browser fetching, JS-shell detection, recovery, and technical triage. Page analysis owns cleaning, quality checks, and semantic classification. `ToolExecutor` executes tools and records tool events.

`job_radar/extractors/` owns the boundary from `PageDocument` to `RawJobRecord`. `RuleBasedJobExtractor` is the current implementation and fallback. `LLMJobExtractor` is the adapter for future AI-backed extraction.

`job_radar/pipeline/` contains deterministic data processing only: validation, normalization, deduplication, matching, and runner orchestration. It does not call an LLM, web search, or Streamlit.

`job_radar/storage/` owns SQLite schema and repository methods. User-managed fields such as status and notes must be preserved on re-import.

`job_radar/services/` exposes use cases to UI and tests. It wires profile config, tools, agent orchestration, pipeline runner, and repository.

`app.py` is the Streamlit entry point. It should call services and never execute SQL or provider calls directly.

## Removed Overlap

The old `collectors/`, plural `agents/`, and `llm/` packages were removed to avoid duplicate responsibilities:

- Agent flow control is now `agent/orchestrator.py`.
- Profile/search decisions are now `ai/tasks/`.
- Ollama/model invocation belongs in `infra/llm/`.

This keeps each module focused on one question:

```text
AI tasks: how should AI decide?
Tools: what action should be executed?
Agent: what step runs next?
Pipeline: how is data cleaned and constrained?
Storage: how is data persisted safely?
UI: how is the result shown?
```
