# Project Structure

```text
job-radar/
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
|   |-- demo_jobs.csv
|   `-- .gitkeep
|-- docs/
|   |-- architecture.md
|   |-- pipeline.md
|   `-- project_structure.md
|-- job_radar/
|   |-- __init__.py
|   |-- config.py
|   |-- agents/
|   |   |-- __init__.py
|   |   |-- discovery.py
|   |   |-- models.py
|   |   |-- profile.py
|   |   `-- search_plan.py
|   |-- collectors/
|   |   |-- __init__.py
|   |   |-- agent.py
|   |   |-- base.py
|   |   `-- demo.py
|   |-- extractors/
|   |   |-- __init__.py
|   |   `-- rule_based.py
|   |-- llm/
|   |   |-- __init__.py
|   |   |-- base.py
|   |   `-- mock.py
|   |-- models/
|   |   |-- __init__.py
|   |   |-- job.py
|   |   `-- profile.py
|   |-- pipeline/
|   |   |-- __init__.py
|   |   |-- validation.py
|   |   |-- normalization.py
|   |   |-- deduplication.py
|   |   |-- matching.py
|   |   `-- runner.py
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
|   |   |-- factory.py
|   |   |-- http_page_collector.py
|   |   |-- manual_sources.py
|   |   |-- mock_page_collector.py
|   |   `-- mock_web_search.py
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

## Main Modules

`app.py` is the Streamlit entry point. It calls services and contains no SQL.

`job_radar/models/` defines `RawJobRecord`, `JobRecord`, `UserProfile`, and `MatchingRules`.

`job_radar/agents/` coordinates profile checks, search planning, tool calls, URL selection, page collection, and extraction. It depends on the `JobExtractor` interface instead of a concrete LLM client.

`job_radar/collectors/` contains pipeline-facing collectors. `DemoCollector` reads local CSV demo data. `AgentDiscoveryCollector` adapts the agent result into the same `RawJobRecord` list expected by `PipelineRunner`.

`job_radar/extractors/` contains the `JobExtractor` interface and implementations. `RuleBasedJobExtractor` handles mock marker blocks and simple Chinese JD detail pages. `LLMJobExtractor` is the future adapter for a real LLM client.

`job_radar/llm/` defines the LLM client interface and a deterministic mock client for tests. No real LLM API key is required in the current phase.

`job_radar/tools/` defines tool interfaces and scheduler wiring. Current tools include mock web search, mock page collection, manually configured URL sources, and a Python HTTP page collector for explicit URLs in `config/sources.example.yaml`.

`job_radar/pipeline/` contains the stable local processing steps: validation, normalization, deduplication, matching, and orchestration.

`job_radar/storage/` owns SQLite initialization and parameterized repository methods. It reports whether each upsert inserted, updated, or failed.

`job_radar/services/` provides application use cases consumed by Streamlit, including demo ingestion, mock agent ingestion, manual URL ingestion, job listing, status updates, notes updates, and CSV export.

`job_radar/utils/` contains shared paths and logging helpers.

`tests/` verifies models, collectors, agent tools, extraction, pipeline behavior, repository persistence, and app import behavior. Tests use temporary databases and do not write to `data/jobs.db`.

## Local Data

`data/jobs.db` is created at runtime and ignored by Git. `data/demo_jobs.csv` is safe to commit because it contains demo records only.

`config/profile.yaml`, `config/sources.yaml`, and `config/matching_rules.yaml` are private local files. If they are absent, the app falls back to the `.example.yaml` files.
