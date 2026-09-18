"""Collect candidate pages and run deterministic pre-extraction filtering."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from job_radar.tools.web_search.models import CandidateSource, SearchPlan
from job_radar.tools.page_acquisition.models import PageDocument
from job_radar.tools.page_analysis.triage import (
    RejectedPage,
    triage_pages,
    summarize_page_signals,
)
from job_radar.tools.page_analysis.models import PendingFollowup
from job_radar.tools.page_acquisition.pipeline import PageAcquisitionPipeline


def main(argv: list[str] | None = None) -> int:
    """Fetch CandidateSource URLs and print filter summaries."""

    parser = argparse.ArgumentParser(description="Collect pages and filter obvious non-JD pages.")
    parser.add_argument("--sources-file", required=True, help="Path to CandidateSource[] JSON.")
    parser.add_argument("--plan-file", help="Optional SearchPlan JSON used for extra signal matching.")
    parser.add_argument("--min-text-length", type=int, default=300)
    parser.add_argument("--timeout-seconds", type=int, default=20)
    parser.add_argument("--snippet-chars", type=int, default=500)
    parser.add_argument(
        "--output-readable-pages-file",
        help="Optional path to write readable PageDocument[] with full text, html, and metadata.",
    )
    parser.add_argument(
        "--output-pending-file",
        help="Optional path to write pending pages that need another collection method.",
    )
    parser.add_argument(
        "--output-pending-followups-file",
        help="Optional path to write agent-ready pending follow-up records.",
    )
    parser.add_argument(
        "--output-report-file",
        help="Optional path to write the same filter summary printed to stdout.",
    )
    parser.add_argument(
        "--output-run-dir",
        help=(
            "Optional artifact directory. Overwrites readable_pages.json, pending_pages.json, "
            "and page_acquisition_report.json in that directory."
        ),
    )
    args = parser.parse_args(argv)

    try:
        sources = _load_sources(args.sources_file)
        plan = _load_plan(args.plan_file) if args.plan_file else None
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        print(f"Invalid input: {exc}", file=sys.stderr)
        return 2

    tool = PageAcquisitionPipeline(timeout_seconds=args.timeout_seconds)
    pages: list[PageDocument] = []
    pending_fetches: list[PendingFollowup] = []
    rejected_fetches: list[RejectedPage] = []
    for source in sources:
        try:
            pages.append(tool.run(source))
        except Exception as exc:
            if _is_pending_fetch_error(exc):
                pending_fetches.append(
                    PendingFollowup(
                        url=source.url,
                        source_name=source.source_name,
                        title=source.title,
                        reasons=[f"fetch_error: {exc}"],
                        pending_kind="recovery_required",
                        suggested_next_action="manual_review",
                        company_name=source.company_name,
                        company_type=source.company_type,
                        is_official=source.is_official,
                        stage="collection",
                    )
                )
            else:
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

    triage = triage_pages(pages, search_plan=plan, min_text_length=args.min_text_length)
    readable_pages = triage.readable_pages
    pending_pages = triage.recoverable_pages
    rejected_pages = [*triage.rejected_pages, *rejected_fetches]

    pending_followups = pending_fetches
    summary = _summarize_result(readable_pages, pending_pages, rejected_pages, plan, args.snippet_chars)
    summary["pending_followup_count"] = len(pending_followups)
    summary["pending_followups"] = [item.model_dump() for item in pending_followups]
    summary["collected_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    output_readable_pages_file = args.output_readable_pages_file
    output_pending_file = args.output_pending_file
    output_pending_followups_file = args.output_pending_followups_file
    output_report_file = args.output_report_file
    try:
        run_dir = Path(args.output_run_dir) if args.output_run_dir else None
        if run_dir:
            output_readable_pages_file = output_readable_pages_file or str(run_dir / "readable_pages.json")
            output_pending_file = output_pending_file or str(run_dir / "pending_pages.json")
            output_pending_followups_file = output_pending_followups_file or str(run_dir / "pending_followups.json")
            output_report_file = output_report_file or str(run_dir / "page_acquisition_report.json")
            summary["artifacts"] = {"run_dir": str(run_dir)}
        if output_readable_pages_file:
            _write_json(
                output_readable_pages_file,
                [page.model_dump() for page in readable_pages],
            )
        if output_pending_file:
            _write_json(
                output_pending_file,
                [page.model_dump() for page in pending_pages],
            )
        if output_pending_followups_file:
            _write_json(
                output_pending_followups_file,
                [item.model_dump() for item in pending_followups],
            )
        if output_report_file:
            summary.setdefault("artifacts", {})
            summary["artifacts"].update(
                {
                    key: value
                    for key, value in {
                        "readable_pages_file": output_readable_pages_file,
                        "pending_pages_file": output_pending_file,
                        "pending_followups_file": output_pending_followups_file,
                        "report_file": output_report_file,
                    }.items()
                    if value
                }
            )
            _write_json(output_report_file, summary)
    except OSError as exc:
        print(f"Failed to write output file: {exc}", file=sys.stderr)
        return 4

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _load_sources(path: str) -> list[CandidateSource]:
    with open(path, encoding="utf-8-sig") as file:
        return TypeAdapter(list[CandidateSource]).validate_python(json.load(file))


def _load_plan(path: str) -> SearchPlan:
    with open(path, encoding="utf-8-sig") as file:
        return SearchPlan.model_validate(json.load(file))


def _write_json(path: str, payload: object) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _is_pending_fetch_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(
        marker in text
        for marker in [
            "403",
            "forbidden",
            "429",
            "too many requests",
            "timed out",
            "timeout",
            "winerror 10013",
        ]
    )


def _summarize_result(readable_pages, pending_pages, rejected_pages, plan: SearchPlan | None, snippet_chars: int) -> dict:
    return {
        "readable_count": len(readable_pages),
        "pending_count": len(pending_pages),
        "rejected_count": len(rejected_pages),
        "readable_pages": [
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
            for page in readable_pages
        ],
        "pending_pages": [
            {
                "url": page.url,
                "final_url": page.metadata.get("final_url"),
                "status_code": page.metadata.get("status_code"),
                "source_name": page.source_name,
                "title": page.title,
                "text_length": len(page.text),
                "reasons": [],
                "signals": summarize_page_signals(page, plan),
                "snippet": page.text[:snippet_chars],
            }
            for page in pending_pages
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
            for page in rejected_pages
        ],
    }


if __name__ == "__main__":
    raise SystemExit(main())


