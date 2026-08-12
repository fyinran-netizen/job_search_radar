"""Extract RawJobRecord objects from cleaned pages and prepare them for analysis."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from urllib.parse import unquote, urlparse

from pydantic import TypeAdapter, ValidationError

from job_radar.ai.providers.base import AIProvider
from job_radar.ai.providers.codex_cli import CodexCliProvider
from job_radar.ai.providers.ollama import OllamaProvider
from job_radar.ai.tasks.job_extraction import AIJobExtractionClient, AIPageInput
from job_radar.extractors.rule_based import RuleBasedJobExtractor
from job_radar.models.job import RawJobRecord
from job_radar.models.page_triage import PendingFollowup
from job_radar.models.tool import PageContent
from job_radar.pipeline.extraction_reliability import (
    ExtractionReliabilityError,
    validate_extracted_page_coverage,
)
from job_radar.pipeline.job_preparation import prepare_records_for_analysis
from job_radar.pipeline.page_triage import triage_extracted_page


def main(argv: list[str] | None = None) -> int:
    """Run job extraction from cleaned AIPageInput records."""

    parser = argparse.ArgumentParser(
        description="Extract jobs from cleaned pages, then validate, normalize, and deduplicate them."
    )
    parser.add_argument("--cleaned-pages-file", required=True, help="Path to cleaned AIPageInput[] JSON.")
    parser.add_argument(
        "--provider",
        choices=["ollama", "codex", "rule-based"],
        default=os.environ.get("JOB_RADAR_EXTRACTION_PROVIDER", "ollama"),
        help="Extraction provider. ollama uses the local Ollama API; codex uses Codex CLI; rule-based is testing fallback.",
    )
    parser.add_argument("--timeout-seconds", type=int, default=240)
    parser.add_argument("--max-attempts", type=int, default=3, help="Maximum AI attempts per page batch.")
    parser.add_argument("--max-pages", type=int, help="Optional maximum number of cleaned pages to extract.")
    parser.add_argument("--batch-size", type=int, default=8, help="Number of pages per AI extraction call.")
    parser.add_argument(
        "--ollama-model",
        default=os.environ.get("JOB_RADAR_EXTRACTION_OLLAMA_MODEL", os.environ.get("OLLAMA_MODEL", "qwen3.5:cloud")),
        help="Ollama model name for --provider ollama.",
    )
    parser.add_argument(
        "--ollama-base-url",
        default=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"),
        help="Local Ollama server base URL for --provider ollama.",
    )
    parser.add_argument("--output-run-dir", help="Artifact directory for prepared_jobs.json.")
    parser.add_argument("--prepared-jobs-file", help="Optional path for prepared JobRecord[] JSON.")
    parser.add_argument("--output-report-file", help="Optional path to write the extraction report JSON.")
    args = parser.parse_args(argv)

    try:
        page_inputs = _load_cleaned_pages(args.cleaned_pages_file)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        print(f"Invalid cleaned pages input: {exc}", file=sys.stderr)
        return 2

    if args.max_pages is not None:
        page_inputs = page_inputs[: args.max_pages]
    print(f"Loaded {len(page_inputs)} cleaned page(s). Provider: {args.provider}.", file=sys.stderr, flush=True)

    run_started = perf_counter()
    extraction_started = perf_counter()
    try:
        raw_records, extraction_errors, retry_count, pending_followups = _extract_records(
            page_inputs,
            provider_name=args.provider,
            timeout_seconds=args.timeout_seconds,
            batch_size=args.batch_size,
            ollama_model=args.ollama_model,
            ollama_base_url=args.ollama_base_url,
            max_attempts=args.max_attempts,
        )
    except KeyboardInterrupt:
        print("Job extraction interrupted by user.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Job extraction failed: {exc}", file=sys.stderr)
        return 3
    extraction_seconds = perf_counter() - extraction_started

    preparation_started = perf_counter()
    preparation = prepare_records_for_analysis(raw_records)
    preparation_seconds = perf_counter() - preparation_started
    errors = [*extraction_errors, *preparation.errors]

    run_dir = Path(args.output_run_dir) if args.output_run_dir else None
    prior_pending_followups = _load_prior_pending_followups(run_dir) if run_dir else []
    all_pending_followups = _merge_pending_followups(prior_pending_followups, pending_followups)
    report = {
        "extracted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provider": args.provider,
        "page_count": len(page_inputs),
        "extracted_count": len(raw_records),
        "valid_count": preparation.valid_count,
        "invalid_count": preparation.invalid_count,
        "duplicate_count": preparation.duplicate_count,
        "prepared_count": len(preparation.prepared_records),
        "extraction_error_count": len(extraction_errors),
        "new_pending_followup_count": len(pending_followups),
        "prior_pending_followup_count": len(prior_pending_followups),
        "pending_followup_count": len(all_pending_followups),
        "retry_count": retry_count,
        "timing": {
            "extraction_seconds": round(extraction_seconds, 3),
            "preparation_seconds": round(preparation_seconds, 3),
            "total_seconds": round(perf_counter() - run_started, 3),
        },
        "errors": errors,
        "duplicate_jobs": [record.model_dump() for record in preparation.duplicate_records],
        "pending_followups": [item.model_dump() for item in all_pending_followups],
    }

    prepared_jobs_file = args.prepared_jobs_file
    output_report_file = args.output_report_file
    if run_dir:
        prepared_jobs_file = prepared_jobs_file or str(run_dir / "prepared_jobs.json")
        pending_followups_file = str(run_dir / "pending_followups.json")
        output_report_file = output_report_file or str(run_dir / "job_extraction_report.json")
        report["artifacts"] = {
            "run_dir": str(run_dir),
            "prepared_jobs_file": prepared_jobs_file,
            "pending_followups_file": pending_followups_file,
            "report_file": output_report_file,
        }
    else:
        pending_followups_file = None

    try:
        if prepared_jobs_file:
            _write_json(prepared_jobs_file, [record.model_dump() for record in preparation.prepared_records])
        if pending_followups_file:
            _write_json(pending_followups_file, [item.model_dump() for item in all_pending_followups])
        if output_report_file:
            _write_json(output_report_file, report)
    except OSError as exc:
        print(f"Failed to write output file: {exc}", file=sys.stderr)
        return 4

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _load_cleaned_pages(path: str) -> list[AIPageInput]:
    with open(path, encoding="utf-8-sig") as file:
        return TypeAdapter(list[AIPageInput]).validate_python(json.load(file))


def _load_prior_pending_followups(run_dir: Path) -> list[PendingFollowup]:
    collection_report = run_dir / "page_collection_report.json"
    if collection_report.exists():
        try:
            payload = json.loads(collection_report.read_text(encoding="utf-8-sig"))
            return TypeAdapter(list[PendingFollowup]).validate_python(payload.get("pending_followups", []))
        except (OSError, json.JSONDecodeError, ValidationError):
            return []

    pending_file = run_dir / "pending_followups.json"
    if pending_file.exists():
        try:
            payload = json.loads(pending_file.read_text(encoding="utf-8-sig"))
            return TypeAdapter(list[PendingFollowup]).validate_python(payload)
        except (OSError, json.JSONDecodeError, ValidationError):
            return []
    return []


def _merge_pending_followups(
    prior_items: list[PendingFollowup],
    new_items: list[PendingFollowup],
) -> list[PendingFollowup]:
    merged: dict[tuple[str, str, str], PendingFollowup] = {}
    for item in [*prior_items, *new_items]:
        merged[(item.url, item.pending_kind, item.stage)] = item
    return list(merged.values())


def _extract_records(
    page_inputs: list[AIPageInput],
    provider_name: str,
    timeout_seconds: int,
    batch_size: int,
    ollama_model: str,
    ollama_base_url: str,
    max_attempts: int,
) -> tuple[list[RawJobRecord], list[dict[str, object]], int, list]:
    records: list[RawJobRecord] = []
    errors: list[dict[str, object]] = []
    pending_followups = []
    retry_count = 0

    if provider_name in {"codex", "ollama"}:
        if batch_size < 1:
            raise ValueError("--batch-size must be greater than 0")
        if max_attempts < 1:
            raise ValueError("--max-attempts must be greater than 0")
        provider = _create_ai_provider(
            provider_name,
            ollama_model=ollama_model,
            ollama_base_url=ollama_base_url,
        )
        client = AIJobExtractionClient(
            provider,
            timeout_seconds=timeout_seconds,
        )
        for start in range(0, len(page_inputs), batch_size):
            batch = page_inputs[start : start + batch_size]
            _print_batch_progress("extracting", start + 1, start + len(batch), len(page_inputs), batch)
            batch_started = perf_counter()
            page_records = None
            last_error: Exception | None = None
            for attempt in range(1, max_attempts + 1):
                retry_instruction = None
                if attempt > 1:
                    retry_instruction = (
                        "A previous attempt did not produce a usable complete extraction. This is "
                        "public job posting data; perform the extraction and return JSON only."
                    )
                try:
                    page_records = client.extract_jobs_from_inputs(
                        batch,
                        retry_instruction=retry_instruction,
                    )
                    validate_extracted_page_coverage(
                        page_records,
                        [page_input.url for page_input in batch],
                    )
                    break
                except Exception as exc:
                    last_error = exc
                    if attempt >= max_attempts:
                        break
                    retry_count += 1
                    _print_batch_progress(
                        "retrying",
                        start + 1,
                        start + len(batch),
                        len(page_inputs),
                        batch,
                        f"attempt {attempt + 1}/{max_attempts} after {_error_summary(exc)}",
                    )
            if page_records is None:
                elapsed = perf_counter() - batch_started
                assert last_error is not None
                for offset, page_input in enumerate(batch, start=start + 1):
                    stage = (
                        "reliability_validation"
                        if isinstance(last_error, ExtractionReliabilityError)
                        else "extraction"
                    )
                    errors.append(_extraction_error(offset, page_input, last_error, stage=stage))
                _print_batch_progress(
                    "failed",
                    start + 1,
                    start + len(batch),
                    len(page_inputs),
                    batch,
                    f"{_error_summary(last_error)} in {elapsed:.2f}s",
                )
                continue
            elapsed = perf_counter() - batch_started
            backfilled_records = _backfill_batch_records(page_records, batch)
            accepted_records, pending_items = _triage_extracted_records(backfilled_records, batch)
            records.extend(accepted_records)
            pending_followups.extend(pending_items)
            _print_batch_progress(
                "extracted",
                start + 1,
                start + len(batch),
                len(page_inputs),
                batch,
                f"{len(accepted_records)} accepted record(s), {len(pending_items)} pending page(s) in {elapsed:.2f}s",
            )
        return records, errors, retry_count, pending_followups

    extractor = RuleBasedJobExtractor()
    for index, page_input in enumerate(page_inputs, start=1):
        _print_progress("extracting", index, len(page_inputs), page_input)
        page_started = perf_counter()
        try:
            page_records = extractor.extract(_page_input_to_page_content(page_input))
        except Exception as exc:
            elapsed = perf_counter() - page_started
            errors.append(_extraction_error(index, page_input, exc))
            _print_progress("failed", index, len(page_inputs), page_input, f"{exc} in {elapsed:.2f}s")
            continue
        elapsed = perf_counter() - page_started
        backfilled_records = _backfill_records(page_records, page_input)
        pending = triage_extracted_page(page_input, backfilled_records)
        if pending:
            pending_followups.append(pending)
        else:
            records.extend(backfilled_records)
        _print_progress(
            "extracted",
            index,
            len(page_inputs),
            page_input,
            f"{0 if pending else len(backfilled_records)} accepted record(s) in {elapsed:.2f}s",
        )
    return records, errors, retry_count, pending_followups


def _error_summary(exc: Exception, max_chars: int = 240) -> str:
    text = " ".join(str(exc).split())
    return text if len(text) <= max_chars else text[: max_chars - 3] + "..."


def _triage_extracted_records(
    records: list[RawJobRecord],
    page_inputs: list[AIPageInput],
) -> tuple[list[RawJobRecord], list]:
    accepted_records: list[RawJobRecord] = []
    pending_followups = []
    unassigned_records = list(records)
    for page_input in page_inputs:
        page_records = [
            record
            for record in unassigned_records
            if _record_belongs_to_page(record, page_input)
        ]
        if not page_records and len(page_inputs) == 1:
            page_records = unassigned_records
        for record in page_records:
            if record in unassigned_records:
                unassigned_records.remove(record)
        pending = triage_extracted_page(page_input, page_records)
        if pending:
            pending_followups.append(pending)
        else:
            accepted_records.extend(page_records)
    accepted_records.extend(unassigned_records)
    return accepted_records, pending_followups


def _record_belongs_to_page(record: RawJobRecord, page_input: AIPageInput) -> bool:
    if not record.source_url:
        return False
    return record.source_url in {page_input.url, page_input.final_url}


def _create_ai_provider(provider_name: str, ollama_model: str, ollama_base_url: str) -> AIProvider:
    if provider_name == "codex":
        codex_provider = CodexCliProvider()
        if not codex_provider.is_available():
            raise RuntimeError("Codex CLI is not installed or not authenticated. Run `codex login` first.")
        return codex_provider

    ollama_provider = OllamaProvider(model=ollama_model, base_url=ollama_base_url)
    if not ollama_provider.is_available():
        raise RuntimeError(
            f"Ollama server is not reachable at {ollama_base_url}. "
            "Start Ollama and sign in with `ollama signin` for cloud models."
        )
    return ollama_provider


def _print_batch_progress(
    status: str,
    start: int,
    end: int,
    total: int,
    batch: list[AIPageInput],
    detail: str = "",
) -> None:
    title = batch[0].title.replace("\n", " ")[:80] if batch else ""
    suffix = f" - {detail}" if detail else ""
    print(f"[{start}-{end}/{total}] {status}: {title}{suffix}", file=sys.stderr, flush=True)


def _print_progress(
    status: str,
    index: int,
    total: int,
    page_input: AIPageInput,
    detail: str = "",
) -> None:
    title = page_input.title.replace("\n", " ")[:80]
    suffix = f" - {detail}" if detail else ""
    print(f"[{index}/{total}] {status}: {title}{suffix}", file=sys.stderr, flush=True)


def _backfill_records(records: list[RawJobRecord], page_input: AIPageInput) -> list[RawJobRecord]:
    backfilled: list[RawJobRecord] = []
    for record in records:
        data = record.model_dump()
        data["source_url"] = data.get("source_url") or page_input.url
        data["source_name"] = data.get("source_name") or _infer_source_name(page_input)
        data["apply_url"] = data.get("apply_url") or _first_apply_url(page_input)
        backfilled.append(RawJobRecord.model_validate(data))
    return backfilled


def _backfill_batch_records(records: list[RawJobRecord], page_inputs: list[AIPageInput]) -> list[RawJobRecord]:
    pages_by_url = {page.url: page for page in page_inputs}
    pages_by_final_url = {
        page.final_url: page
        for page in page_inputs
        if page.final_url
    }
    backfilled: list[RawJobRecord] = []
    for record in records:
        page_input = None
        if record.source_url:
            page_input = pages_by_url.get(record.source_url) or pages_by_final_url.get(record.source_url)
        if page_input is None and len(page_inputs) == 1:
            page_input = page_inputs[0]
        if page_input is None:
            backfilled.append(record)
            continue
        backfilled.extend(_backfill_records([record], page_input))
    return backfilled


def _page_input_to_page_content(page_input: AIPageInput) -> PageContent:
    return PageContent(
        url=page_input.url,
        source_name=_infer_source_name(page_input),
        title=page_input.title,
        text=page_input.visible_text,
        metadata={
            "final_url": page_input.final_url,
            "company_name": page_input.source_company_name,
            "company_type": page_input.company_type,
            "is_official": page_input.is_official,
            "links": [
                {"href": link.url, "text": link.text, "kind": link.kind}
                for link in page_input.important_links
            ],
        },
    )


def _infer_source_name(page_input: AIPageInput) -> str:
    parsed = urlparse(page_input.final_url or page_input.url)
    if parsed.netloc:
        return parsed.netloc
    if parsed.scheme == "file" and parsed.path:
        return Path(unquote(parsed.path)).stem
    if parsed.scheme:
        return parsed.scheme
    return page_input.title or page_input.url


def _first_apply_url(page_input: AIPageInput) -> str | None:
    for link in page_input.important_links:
        if link.kind == "apply":
            return link.url
    return None


def _extraction_error(
    index: int,
    page_input: AIPageInput,
    exc: Exception,
    stage: str = "extraction",
) -> dict[str, object]:
    return {
        "stage": stage,
        "index": index,
        "url": page_input.url,
        "title": page_input.title,
        "reason": str(exc),
    }


def _write_json(path: str, payload: object) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
