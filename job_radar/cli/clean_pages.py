"""Clean accepted PageContent records into AI extraction inputs."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from job_radar.ai.tasks.job_extraction import AIPageInput, extract_important_links
from job_radar.models.tool import PageContent
from job_radar.pipeline.page_cleaning import clean_page_text


def main(argv: list[str] | None = None) -> int:
    """Convert accepted PageContent[] into cleaned AIPageInput[]."""

    parser = argparse.ArgumentParser(description="Clean accepted pages before AI extraction.")
    parser.add_argument("--pages-file", required=True, help="Path to accepted PageContent[] JSON.")
    parser.add_argument("--output-file", required=True, help="Path to write cleaned AIPageInput[] JSON.")
    parser.add_argument("--report-file", help="Optional path to write cleaning report JSON.")
    parser.add_argument("--max-text-chars", type=int, default=12000)
    parser.add_argument("--min-extracted-chars", type=int, default=300)
    args = parser.parse_args(argv)

    try:
        pages = _load_pages(args.pages_file)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        print(f"Invalid pages input: {exc}", file=sys.stderr)
        return 2

    cleaned_inputs: list[AIPageInput] = []
    report_pages: list[dict] = []
    for page in pages:
        final_url = page.metadata.get("final_url")
        cleaned = clean_page_text(
            page.html,
            page.text,
            url=page.url,
            max_text_chars=args.max_text_chars,
            min_extracted_chars=args.min_extracted_chars,
        )
        important_links = extract_important_links(page)
        cleaned_inputs.append(
            AIPageInput(
                url=page.url,
                final_url=final_url if isinstance(final_url, str) else None,
                source_name=page.source_name,
                source_company_name=_metadata_string(page, "company_name"),
                company_type=_metadata_string(page, "company_type"),
                is_official=bool(page.metadata.get("is_official", False)),
                title=page.title,
                visible_text=cleaned.text,
                important_links=important_links,
            )
        )
        report_pages.append(
            {
                "url": page.url,
                "title": page.title,
                "source_name": page.source_name,
                "method": cleaned.method,
                "original_chars": cleaned.original_chars,
                "cleaned_chars": cleaned.cleaned_chars,
                "original_line_count": cleaned.original_line_count,
                "kept_line_count": cleaned.kept_line_count,
                "removed_line_count": cleaned.removed_line_count,
                "important_link_count": len(important_links),
                "truncated": cleaned.truncated,
            }
        )

    report = {
        "cleaned_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "page_count": len(cleaned_inputs),
        "max_text_chars": args.max_text_chars,
        "min_extracted_chars": args.min_extracted_chars,
        "output_file": args.output_file,
        "pages": report_pages,
    }

    try:
        _write_json(args.output_file, [item.model_dump() for item in cleaned_inputs])
        if args.report_file:
            _write_json(args.report_file, report)
    except OSError as exc:
        print(f"Failed to write output file: {exc}", file=sys.stderr)
        return 4

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _load_pages(path: str) -> list[PageContent]:
    with open(path, encoding="utf-8-sig") as file:
        return TypeAdapter(list[PageContent]).validate_python(json.load(file))


def _metadata_string(page: PageContent, key: str) -> str | None:
    value = page.metadata.get(key)
    return value if isinstance(value, str) and value.strip() else None


def _write_json(path: str, payload: object) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
