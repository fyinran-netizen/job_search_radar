# Job Radar Agent Notes

## Project Goal
Job Radar is a local-first job discovery, matching, and application tracking tool. The current phase proves the architecture and end-to-end demo pipeline; it is not a real recruitment crawler yet.

## Tech Stack
- Python 3.11+
- uv for dependency management
- Streamlit for the local UI
- SQLite for persistence
- pandas for CSV/table handling
- Pydantic for models
- PyYAML for configuration
- pytest for tests

## Current Pipeline
`Collector -> RawJobRecord -> Validation -> Normalization -> Deduplication -> Matching -> Repository -> Service -> Streamlit`

The demo pipeline uses `DemoCollector` and `data/demo_jobs.csv`. Invalid single records must be reported without failing the whole run.

The mock agent pipeline uses deterministic `ProfileCompletenessChecker`, deterministic `SearchPlanBuilder`, `ToolScheduler`, `MockWebSearchTool`, `MockPageCollectorTool`, `RuleBasedJobExtractor`, and `AgentDiscoveryCollector`. It must not make network requests or call a real LLM API.

The manual URL pipeline uses `ManualSourceTool`, `HttpPageCollectorTool`, `RuleBasedJobExtractor`, and `AgentDiscoveryCollector`. It may fetch explicitly configured JD URLs from `config/sources.yaml` or `config/sources.example.yaml`, but it must not perform automatic search, broad crawling, Playwright automation, or LLM API calls in the current phase.

## Module Boundaries
- `collectors/`: read raw records from a source.
- `agents/`: coordinate profile checks, search planning, tool calls, source selection, and extraction.
- `llm/`: define LLM interfaces for steps that need AI-style extraction or analysis.
- `extractors/`: convert page text into `RawJobRecord` objects. Current runtime uses `RuleBasedJobExtractor`; future LLM extraction should plug in through `LLMJobExtractor`.
- `tools/`: define tool interfaces, scheduling, mock external tools, manual source loading, and HTTP page collection.
- `pipeline/`: validation, normalization, deduplication, matching, and orchestration.
- `storage/`: SQLite schema and repository methods only.
- `services/`: application-level use cases consumed by the UI.
- `app.py`: Streamlit presentation only; no direct SQL.

## Code Style
- Use type annotations and pathlib.
- Use parameterized SQL.
- Keep modules small and purposeful.
- Avoid adding empty placeholder interfaces.
- Dates are ISO 8601 strings.

## Tests
After changes, run:

```bash
uv run pytest
```

For UI startup checks, run:

```bash
uv run streamlit run app.py
```

## Adding Collectors
New collectors should return `RawJobRecord` objects, preserve source URLs, and avoid collecting personal data. Do not add real web crawling, Playwright, login flows, or automated application behavior in this phase.

New tools should be callable through `ToolScheduler` and return structured Pydantic models or dictionaries. Automatic web search and broad collectors should be added only in a later phase.

## Privacy
Never commit real names, emails, phone numbers, resumes, private notes, personal configs, local databases, or real application history.
