"""Understand prepared jobs with basic gates and local Ollama."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from pydantic import TypeAdapter, ValidationError

from job_radar.config import load_runtime_settings
from job_radar.infra.llm.ollama import OllamaProvider
from job_radar.tools.job_understanding.analyzer import JobUnderstandingAnalyzer
from job_radar.tools.job_extraction.backend_gate.gate import evaluate_basic_gate
from job_radar.config import load_profile
from job_radar.tools.job_extraction.models import JobRecord
from job_radar.infra.paths import CONFIG_DIR


def main(argv: list[str] | None = None) -> int:
    """Run basic gate and AI job understanding for prepared JobRecord[] artifacts."""

    settings = load_runtime_settings()
    parser = argparse.ArgumentParser(
        description="Understand prepared jobs with deterministic basic gates and one Ollama call per continuing job."
    )
    parser.add_argument("--prepared-jobs-file", required=True, help="Path to prepared JobRecord[] JSON.")
    parser.add_argument("--profile-dir", default=str(CONFIG_DIR), help="Directory containing profile.yaml or profile.example.yaml.")
    parser.add_argument("--output-file", required=True, help="Path for JobUnderstandingRecord[] JSON.")
    parser.add_argument("--max-jobs", type=int, help="Optional maximum number of prepared jobs to understand.")
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument(
        "--ollama-model",
        default=settings.understanding.model,
        help="Ollama model name.",
    )
    parser.add_argument(
        "--ollama-base-url",
        default=settings.ollama_base_url,
        help="Local Ollama server base URL.",
    )
    args = parser.parse_args(argv)

    try:
        jobs = _load_prepared_jobs(args.prepared_jobs_file)
        profile, used_example_profile, profile_path = load_profile(Path(args.profile_dir))
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        print(f"Invalid understanding input: {exc}", file=sys.stderr)
        return 2

    if args.max_jobs is not None:
        jobs = jobs[: args.max_jobs]

    provider = OllamaProvider(model=args.ollama_model, base_url=args.ollama_base_url)
    if not provider.is_available():
        print(
            f"Ollama server is not reachable at {args.ollama_base_url}. "
            "Start Ollama and make sure the selected model is available.",
            file=sys.stderr,
        )
        return 3

    analyzer = JobUnderstandingAnalyzer(provider, timeout_seconds=args.timeout_seconds)
    started = perf_counter()
    records = []
    errors = []
    for index, job in enumerate(jobs, start=1):
        print(f"[{index}/{len(jobs)}] understanding: {job.company_name} - {job.title}", file=sys.stderr, flush=True)
        try:
            gate = evaluate_basic_gate(job, profile)
            if not gate.should_continue:
                continue
            job = job.model_copy(update={"basic_gate": gate})
            record = analyzer.understand(job, profile)
        except Exception as exc:
            errors.append(
                {
                    "index": index,
                    "company_name": job.company_name,
                    "title": job.title,
                    "deduplication_key": job.deduplication_key,
                    "reason": str(exc),
                }
            )
            continue
        records.append(record)

    try:
        _write_json(args.output_file, [record.model_dump() for record in records])
    except OSError as exc:
        print(f"Failed to write output file: {exc}", file=sys.stderr)
        return 4

    report = {
        "understood_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provider": "ollama",
        "ollama_model": args.ollama_model,
        "profile_file": str(profile_path),
        "used_example_profile": used_example_profile,
        "prepared_count": len(jobs),
        "understanding_count": len(records),
        "error_count": len(errors),
        "errors": errors,
        "artifacts": {
            "output_file": args.output_file,
        },
        "timing": {
            "total_seconds": round(perf_counter() - started, 3),
        },
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 5


def _load_prepared_jobs(path: str) -> list[JobRecord]:
    with open(path, encoding="utf-8-sig") as file:
        return TypeAdapter(list[JobRecord]).validate_python(json.load(file))


def _write_json(path: str, payload: object) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())


