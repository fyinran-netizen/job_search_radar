# Job Radar Agent Notes

## Project Goal
Job Radar is a local-first job discovery, matching, and application tracking tool. The current phase proves the architecture and end-to-end demo pipeline; it is not a real recruitment crawler yet.

The long-term workflow should align with `docs/job_search_agent_full_flow.svg`: program controls the workflow, AI returns structured decisions, tools execute bounded actions, and deterministic code validates, normalizes, deduplicates, persists, and protects user state.

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
`Tool/Extractor -> RawJobRecord -> Validation -> Normalization -> Deduplication -> Matching -> Repository -> Service -> Streamlit`

The demo pipeline uses `DemoCsvTool` and `data/demo_jobs.csv`. Invalid single records must be reported without failing the whole run.

The mock agent pipeline uses deterministic `ProfileCompletenessChecker`, deterministic `SearchPlanBuilder`, `ToolExecutor`, `MockWebSearchTool`, `MockPageTool`, `RuleBasedJobExtractor`, and `JobDiscoveryAgent`. It must not make network requests or call a real LLM API.

The manual URL pipeline uses `ManualSourceTool`, `HttpPageTool`, `RuleBasedJobExtractor`, and `JobDiscoveryAgent`. It may fetch explicitly configured JD URLs from `config/sources.yaml` or `config/sources.example.yaml`, but it must not perform automatic search, broad crawling, Playwright automation, or LLM API calls in the current phase.

Current code is the deterministic core and first tool-execution slice of the target SVG. Future work should add an orchestrator and structured AI decision models around this core, not bypass it.

## Target Agent Direction
- AI should return Pydantic-validated JSON decisions such as `CandidateProfileDecision`, `CompletenessDecision`, `SearchStrategy`, `ToolPlan`, `JobUnderstanding`, `MatchAssessment`, and `ContinueDecision`.
- The orchestrator should validate each AI decision before executing tools or mutating state.
- Tool calls should go through `ToolExecutor`.
- `RuleBasedJobExtractor` is a current mock/fallback. Varied real pages should eventually use `LLMJobExtractor(real_client)` plus validation.
- Search should become iterative only after round limits, budget limits, privacy rules, and run logging are explicit.

## Module Boundaries
- `.agents/skills/`: prompt rules and examples for Codex-style AI tasks.
- `agent/`: coordinate profile checks, search planning, tool calls, source selection, state, limits, and extraction.
- `ai/tasks/`: business-specific AI decisions. Current implementations are deterministic fallbacks.
- `ai/providers/`: provider adapters such as Codex CLI and mock provider. Providers must not contain job-search business logic.
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

## Adding Tools
New tools should return structured Pydantic models or dictionaries, preserve source URLs, and avoid collecting personal data. Do not add real web crawling, Playwright, login flows, or automated application behavior in this phase.

New tools should be callable through `ToolExecutor`. Automatic web search and broad collection should be added only after guardrails, limits, and run logging are explicit.

## Privacy
Never commit real names, emails, phone numbers, resumes, private notes, personal configs, local databases, or real application history.
