"""Classify cleaned pages as job-detail pages before extraction."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from job_radar.ai.providers.ollama import OllamaProvider
from job_radar.ai.tasks.job_extraction import AIPageInput
from job_radar.ai.tasks.page_classification import PageJDClassification, PageJDClassifier
from job_radar.models.page_triage import PendingFollowup


def main(argv: list[str] | None = None) -> int:
    """Classify cleaned AI page inputs and separate clear JDs from pending pages."""

    parser = argparse.ArgumentParser(description="Classify cleaned pages before extraction.")
    parser.add_argument("--cleaned-pages-file", required=True, help="Path to cleaned AIPageInput[] JSON.")
    parser.add_argument("--pending-followups-file", help="Existing PendingFollowup[] JSON to merge.")
    parser.add_argument("--output-jd-cleaned-pages-file", required=True, help="Path to write JD AIPageInput[] JSON.")
    parser.add_argument("--output-pending-followups-file", required=True, help="Path to write merged pending followups.")
    parser.add_argument("--output-report-file", required=True, help="Path to write page classification report.")
    parser.add_argument("--timeout-seconds", type=int, default=90)
    parser.add_argument(
        "--ollama-model",
        default=os.environ.get("JOB_RADAR_PAGE_CLASSIFICATION_OLLAMA_MODEL", "qwen3:8b"),
        help="Ollama model used for page JD classification.",
    )
    parser.add_argument(
        "--ollama-base-url",
        default=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"),
        help="Local Ollama server base URL.",
    )
    args = parser.parse_args(argv)

    try:
        pages = _load_cleaned_pages(args.cleaned_pages_file)
        pending_followups = _load_pending_followups(args.pending_followups_file)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        print(f"Invalid page classification input: {exc}", file=sys.stderr)
        return 2
    existing_pending_count = len(pending_followups)

    provider = OllamaProvider(model=args.ollama_model, base_url=args.ollama_base_url)
    if not provider.is_available():
        print(
            f"Ollama server is not reachable at {args.ollama_base_url}. "
            "Start Ollama before page classification.",
            file=sys.stderr,
        )
        return 3

    classifier = PageJDClassifier(provider, timeout_seconds=args.timeout_seconds)
    jd_pages: list[AIPageInput] = []
    classification_items: list[dict] = []
    errors: list[dict] = []
    for index, page in enumerate(pages, start=1):
        print(f"[{index}/{len(pages)}] classifying: {page.source_name} - {page.title}", file=sys.stderr, flush=True)
        try:
            classification = classifier.classify(page)
        except Exception as exc:
            errors.append(_classification_error(index, page, exc))
            pending_followups.append(_pending_followup_for_error(page, exc))
            continue

        classification_items.append(
            {
                "index": index,
                "url": page.url,
                "title": page.title,
                "source_name": page.source_name,
                "classification": classification.model_dump(),
            }
        )
        if classification.is_job_detail_page:
            jd_pages.append(page)
        else:
            pending_followups.append(_pending_followup_from_classification(page, classification))

    report = {
        "classified_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provider": "ollama",
        "ollama_model": args.ollama_model,
        "input_page_count": len(pages),
        "jd_page_count": len(jd_pages),
        "new_pending_followup_count": len(pending_followups) - existing_pending_count,
        "pending_followup_count": len(pending_followups),
        "error_count": len(errors),
        "errors": errors,
        "classifications": classification_items,
        "artifacts": {
            "input_cleaned_pages_file": args.cleaned_pages_file,
            "output_jd_cleaned_pages_file": args.output_jd_cleaned_pages_file,
            "output_pending_followups_file": args.output_pending_followups_file,
            "report_file": args.output_report_file,
        },
    }

    try:
        _write_json(args.output_jd_cleaned_pages_file, [page.model_dump() for page in jd_pages])
        _write_json(args.output_pending_followups_file, [item.model_dump() for item in pending_followups])
        _write_json(args.output_report_file, report)
    except OSError as exc:
        print(f"Failed to write output file: {exc}", file=sys.stderr)
        return 4

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 5


def _load_cleaned_pages(path: str) -> list[AIPageInput]:
    with open(path, encoding="utf-8-sig") as file:
        return TypeAdapter(list[AIPageInput]).validate_python(json.load(file))


def _load_pending_followups(path: str | None) -> list[PendingFollowup]:
    if not path:
        return []
    try:
        with open(path, encoding="utf-8-sig") as file:
            return TypeAdapter(list[PendingFollowup]).validate_python(json.load(file))
    except FileNotFoundError:
        return []


def _write_json(path: str, payload: object) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _pending_followup_from_classification(
    page: AIPageInput,
    classification: PageJDClassification,
) -> PendingFollowup:
    pending_kind = classification.pending_kind or "not_job_detail_page"
    suggested_next_action = classification.suggested_next_action or "manual_review"
    return PendingFollowup(
        url=page.url,
        final_url=page.final_url,
        title=page.title,
        source_name=page.source_name or _source_name_from_url(page.url),
        company_name=page.source_company_name,
        company_type=page.company_type,
        is_official=page.is_official,
        pending_kind=pending_kind,
        reasons=classification.reasons or ["page classifier did not identify a concrete job detail page"],
        evidence={
            "classifier": classification.model_dump(),
            "text_length": len(page.visible_text),
        },
        suggested_next_action=suggested_next_action,
        priority=80 if pending_kind in {"official_apply_portal", "job_listing_page", "role_list_without_jd"} else 60,
        links=[{"url": link.url, "text": link.text, "kind": link.kind} for link in page.important_links],
        stage="pre_extraction",
    )


def _pending_followup_for_error(page: AIPageInput, exc: Exception) -> PendingFollowup:
    return PendingFollowup(
        url=page.url,
        final_url=page.final_url,
        title=page.title,
        source_name=page.source_name or _source_name_from_url(page.url),
        company_name=page.source_company_name,
        company_type=page.company_type,
        is_official=page.is_official,
        pending_kind="unknown_but_potentially_relevant",
        reasons=[f"classification_error: {exc}"],
        evidence={"text_length": len(page.visible_text)},
        suggested_next_action="manual_review",
        priority=50,
        links=[{"url": link.url, "text": link.text, "kind": link.kind} for link in page.important_links],
        stage="pre_extraction",
    )


def _classification_error(index: int, page: AIPageInput, exc: Exception) -> dict:
    return {
        "index": index,
        "url": page.url,
        "source_name": page.source_name,
        "title": page.title,
        "reason": str(exc),
    }


def _source_name_from_url(url: str) -> str:
    return url.split("/", 3)[2] if "://" in url and len(url.split("/", 3)) > 2 else url


if __name__ == "__main__":
    raise SystemExit(main())
