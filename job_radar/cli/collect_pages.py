"""Collect candidate pages and run deterministic pre-extraction filtering."""

from __future__ import annotations

import argparse
import json
import sys

from pydantic import TypeAdapter, ValidationError

from job_radar.models.search import CandidateSource, SearchPlan
from job_radar.models.tool import PageContent
from job_radar.pipeline.page_filter import RejectedPage, filter_pages, summarize_page_signals
from job_radar.tools.functions.http_page import HttpPageTool


def main(argv: list[str] | None = None) -> int:
    """Fetch CandidateSource URLs and print filter summaries."""

    parser = argparse.ArgumentParser(description="Collect pages and filter obvious non-JD pages.")
    parser.add_argument("--sources-file", required=True, help="Path to CandidateSource[] JSON.")
    parser.add_argument("--plan-file", help="Optional SearchPlan JSON used for extra signal matching.")
    parser.add_argument("--min-text-length", type=int, default=300)
    parser.add_argument("--timeout-seconds", type=int, default=20)
    parser.add_argument("--snippet-chars", type=int, default=500)
    args = parser.parse_args(argv)

    try:
        sources = _load_sources(args.sources_file)
        plan = _load_plan(args.plan_file) if args.plan_file else None
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        print(f"Invalid input: {exc}", file=sys.stderr)
        return 2

    tool = HttpPageTool(timeout_seconds=args.timeout_seconds)
    pages: list[PageContent] = []
    rejected_fetches: list[RejectedPage] = []
    for source in sources:
        try:
            pages.append(tool.run(source))
        except Exception as exc:
            rejected_fetches.append(
                RejectedPage(
                    url=source.url,
                    source_name=source.source_name,
                    title=source.title,
                    reasons=[f"fetch_error: {exc}"],
                    metadata={
                        "company_name": source.company_name,
                        "company_type": source.company_type,
                        "is_official": source.is_official,
                    },
                )
            )

    result = filter_pages(pages, search_plan=plan, min_text_length=args.min_text_length)
    result.rejected_pages.extend(rejected_fetches)
    print(json.dumps(_summarize_result(result, plan, args.snippet_chars), ensure_ascii=False, indent=2))
    return 0


def _load_sources(path: str) -> list[CandidateSource]:
    with open(path, encoding="utf-8-sig") as file:
        return TypeAdapter(list[CandidateSource]).validate_python(json.load(file))


def _load_plan(path: str) -> SearchPlan:
    with open(path, encoding="utf-8-sig") as file:
        return SearchPlan.model_validate(json.load(file))


def _summarize_result(result, plan: SearchPlan | None, snippet_chars: int) -> dict:
    return {
        "accepted_count": len(result.accepted_pages),
        "rejected_count": len(result.rejected_pages),
        "accepted_pages": [
            {
                "url": page.url,
                "final_url": page.metadata.get("final_url"),
                "status_code": page.metadata.get("status_code"),
                "source_name": page.source_name,
                "title": page.title,
                "text_length": len(page.text),
                "signals": summarize_page_signals(page, plan),
                "snippet": page.text[:snippet_chars],
            }
            for page in result.accepted_pages
        ],
        "rejected_pages": [
            {
                "url": page.url,
                "final_url": page.metadata.get("final_url"),
                "status_code": page.metadata.get("status_code"),
                "source_name": page.source_name,
                "title": page.title,
                "text_length": page.text_length,
                "reasons": page.reasons,
            }
            for page in result.rejected_pages
        ],
    }


if __name__ == "__main__":
    raise SystemExit(main())
