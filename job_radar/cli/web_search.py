"""Run one web_search tool call from a static SearchPlan file."""

from __future__ import annotations

import argparse
import json
import sys

from pydantic import ValidationError

from job_radar.ai.providers.codex_cli import CodexCliProvider
from job_radar.models.search import CandidateSource, SearchPlan
from job_radar.tools.executor import ToolExecutor
from job_radar.tools.functions.codex_web_search import CodexWebSearchTool
from job_radar.tools.functions.mock_web_search import MockWebSearchTool


def main(argv: list[str] | None = None) -> int:
    """Run web_search only and print CandidateSource JSON."""

    parser = argparse.ArgumentParser(description="Run Job Radar web_search from a static SearchPlan.")
    parser.add_argument(
        "--provider",
        choices=["codex", "mock"],
        default="codex",
        help="web_search implementation to run.",
    )
    parser.add_argument(
        "--plan-file",
        required=True,
        help="Path to a SearchPlan JSON file.",
    )
    parser.add_argument(
        "--max-sources",
        type=int,
        default=10,
        help="Maximum CandidateSource objects to return.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print prompt and raw Codex CLI stdout/stderr when available.",
    )
    args = parser.parse_args(argv)

    try:
        plan = _load_plan(args.plan_file)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        print(f"Invalid search plan input: {exc}", file=sys.stderr)
        return 2

    codex_provider: CodexCliProvider | None = None
    if args.provider == "codex":
        codex_provider = CodexCliProvider()
        if not codex_provider.is_available():
            print("Codex CLI is not installed or not authenticated. Run `codex login` first.", file=sys.stderr)
            return 3
        tool = CodexWebSearchTool(provider=codex_provider, max_sources=args.max_sources)
    else:
        tool = MockWebSearchTool()

    executor = ToolExecutor([tool])
    try:
        result = executor.run("web_search", plan)
        sources = [
            source if isinstance(source, CandidateSource) else CandidateSource.model_validate(source)
            for source in result
        ]
    except Exception as exc:
        print(f"web_search failed: {exc}", file=sys.stderr)
        if args.debug:
            _print_debug(codex_provider)
        return 3

    print(json.dumps([source.model_dump() for source in sources], ensure_ascii=False, indent=2))
    if args.debug:
        _print_debug(codex_provider)
    return 0


def _load_plan(path: str) -> SearchPlan:
    with open(path, encoding="utf-8-sig") as file:
        return SearchPlan.model_validate(json.load(file))


def _print_debug(codex_provider: CodexCliProvider | None) -> None:
    debug_info = getattr(codex_provider, "last_debug_info", None) if codex_provider else None
    if debug_info is None:
        print("\n--- DEBUG ---", file=sys.stderr)
        print("No Codex CLI call debug info is available.", file=sys.stderr)
        return
    print("\n--- DEBUG: Codex command ---", file=sys.stderr)
    print(" ".join(debug_info.command), file=sys.stderr)
    print("\n--- DEBUG: Prompt sent to Codex ---", file=sys.stderr)
    print(debug_info.prompt, file=sys.stderr)
    print("\n--- DEBUG: Codex stdout ---", file=sys.stderr)
    print(debug_info.stdout or "<empty>", file=sys.stderr)
    print("\n--- DEBUG: Codex stderr ---", file=sys.stderr)
    print(debug_info.stderr or "<empty>", file=sys.stderr)
    print(f"\n--- DEBUG: Codex return code ---\n{debug_info.returncode}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
