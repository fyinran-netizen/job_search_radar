"""Run one web_search tool call from a static SearchPlan file."""

from __future__ import annotations

import argparse
import json
import sys

from pydantic import ValidationError

from job_radar.tools.web_search.models import CandidateSource, SearchPlan
from job_radar.tools.executor import ToolExecutor
from job_radar.tools.web_search.providers.mock import MockWebSearchTool
from job_radar.tools.web_search.providers.tavily import TavilyWebSearchTool


def main(argv: list[str] | None = None) -> int:
    """Run web_search only and print CandidateSource JSON."""

    parser = argparse.ArgumentParser(description="Run Job Radar web_search from a static SearchPlan.")
    parser.add_argument(
        "--provider",
        choices=["tavily", "mock"],
        default="tavily",
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
        help="Retained for CLI compatibility; Tavily does not expose provider debug output.",
    )
    args = parser.parse_args(argv)

    try:
        plan = _load_plan(args.plan_file)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        print(f"Invalid search plan input: {exc}", file=sys.stderr)
        return 2

    if args.provider == "tavily":
        tool = TavilyWebSearchTool(max_sources=args.max_sources)
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
        return 3

    print(json.dumps([source.model_dump() for source in sources], ensure_ascii=False, indent=2))
    return 0


def _load_plan(path: str) -> SearchPlan:
    with open(path, encoding="utf-8-sig") as file:
        return SearchPlan.model_validate(json.load(file))


if __name__ == "__main__":
    raise SystemExit(main())


