"""Create a company-grouped view from prepared JobRecord artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from job_radar.models.job import JobRecord
from job_radar.pipeline.job_grouping import group_jobs_by_company


def main(argv: list[str] | None = None) -> int:
    """Group prepared jobs by company and write a compact review JSON."""

    parser = argparse.ArgumentParser(description="Group prepared JobRecord[] JSON by company.")
    parser.add_argument("--prepared-jobs-file", required=True, help="Path to prepared JobRecord[] JSON.")
    parser.add_argument("--output-file", required=True, help="Path to write company-grouped JSON.")
    args = parser.parse_args(argv)

    try:
        jobs = _load_prepared_jobs(args.prepared_jobs_file)
        grouped = group_jobs_by_company(jobs)
        _write_json(args.output_file, grouped)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        print(f"Failed to group prepared jobs: {exc}", file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "prepared_count": len(jobs),
                "company_count": len(grouped),
                "output_file": args.output_file,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _load_prepared_jobs(path: str) -> list[JobRecord]:
    with open(path, encoding="utf-8-sig") as file:
        return TypeAdapter(list[JobRecord]).validate_python(json.load(file))


def _write_json(path: str, payload: object) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
