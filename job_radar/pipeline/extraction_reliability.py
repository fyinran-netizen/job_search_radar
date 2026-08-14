"""Deterministic reliability checks applied after AI job extraction."""

from job_radar.models.job import RawJobRecord


class ExtractionReliabilityError(RuntimeError):
    """Raised when structurally valid AI output is incomplete for an input page."""


def validate_extracted_page_coverage(
    records: list[RawJobRecord],
    expected_source_urls: list[str],
) -> None:
    """Require at least one extracted record for every JD input page."""

    represented_urls = {record.source_url for record in records if record.source_url}
    missing_urls = [url for url in expected_source_urls if url not in represented_urls]
    if missing_urls:
        raise ExtractionReliabilityError(
            "Program reliability validation found no jobs for JD page(s): "
            + ", ".join(missing_urls)
        )
