"""Agent-facing job extraction tool."""

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from job_radar.infra.logging import get_logger
from job_radar.infra.llm.base import AIProvider
from job_radar.tools.base import BaseTool

from job_radar.tools.job_extraction.extraction import (
    AIJobExtractionClient,
)

from job_radar.tools.page_analysis.models import AIPageInput
from job_radar.tools.job_extraction.models import JobRecord, RawJobRecord
from job_radar.tools.job_extraction.backend_gate.gate import evaluate_basic_gate
from job_radar.profile.models import UserProfile

from job_radar.tools.job_extraction.normalization import (
    deduplicate_records,
    normalize_records,
)

from job_radar.tools.job_extraction.quality import (
    triage_extracted_page,
)

from job_radar.tools.job_extraction.validation import (
    validate_records,
)

from job_radar.tools.page_analysis.models import (
    PendingFollowup,
)


logger = get_logger(__name__)


class JobExtractionInput(BaseModel):
    """Pages ready for job extraction."""

    pages: list[AIPageInput]
    profile: UserProfile | None = None


class JobExtractionOutput(BaseModel):
    """Prepared jobs plus unresolved extraction follow-ups."""

    raw_records: list[
        RawJobRecord
    ] = Field(
        default_factory=list
    )

    prepared_records: list[
        JobRecord
    ] = Field(
        default_factory=list
    )

    duplicate_records: list[
        JobRecord
    ] = Field(
        default_factory=list
    )

    pending_followups: list[
        PendingFollowup
    ] = Field(
        default_factory=list
    )

    report: dict[
        str,
        Any,
    ] = Field(
        default_factory=dict
    )

    def tool_event_summary(
        self,
    ) -> str:

        return (
            f"prepared={len(self.prepared_records)} "
            f"pending={len(self.pending_followups)} "
            f"errors={self.report.get('error_count', 0)}"
        )


class JobExtractionTool(BaseTool):
    """Convert processed JD pages into structured job records."""

    name = "job_extraction"

    def __init__(
        self,
        provider: AIProvider,
        timeout_seconds: int = 240,
    ) -> None:
        self.provider = provider
        self.timeout_seconds = (
            timeout_seconds
        )

    def run(
        self,
        payload: BaseModel | dict[str, Any],
    ) -> JobExtractionOutput:

        data = (
            payload
            if isinstance(
                payload,
                JobExtractionInput,
            )
            else JobExtractionInput.model_validate(
                payload
            )
        )

        client = AIJobExtractionClient(
            provider=self.provider,
            timeout_seconds=(
                self.timeout_seconds
            ),
        )

        all_raw_records: list[
            RawJobRecord
        ] = []

        records_for_preparation: list[
            RawJobRecord
        ] = []

        pending_followups: list[
            PendingFollowup
        ] = []

        extraction_errors: list[
            dict[str, Any]
        ] = []

        for index, page in enumerate(
            data.pages,
            start=1,
        ):
            try:
                page_records = (
                    client.extract_jobs_from_input(page)
                )

            except Exception as exc:
                extraction_errors.append(
                    {
                        "index": index,
                        "url": page.url,
                        "title": page.title,
                        "reason": str(exc),
                    }
                )

                pending = (
                    triage_extracted_page(
                        page,
                        [],
                    )
                )

                if pending:
                    pending_followups.append(
                        pending
                    )

                continue

            all_raw_records.extend(
                page_records
            )

            pending = (
                triage_extracted_page(
                    page,
                    page_records,
                )
            )

            if pending is not None:
                pending_followups.append(
                    pending
                )

                # Sparse/list-like pages should not
                # enter Understanding yet.
                continue

            records_for_preparation.extend(
                page_records
            )

        validation_result = (
            validate_records(
                records_for_preparation
            )
        )

        normalized_records = (
            normalize_records(
                validation_result.valid_records
            )
        )

        deduplication_result = (
            deduplicate_records(
                normalized_records
            )
        )

        gated_records: list[JobRecord] = []
        gate_rejected_count = 0
        for record in deduplication_result.unique_records:
            gate = evaluate_basic_gate(record, data.profile) if data.profile else record.basic_gate
            prepared = record.model_copy(update={"basic_gate": gate})
            if gate.should_continue:
                gated_records.append(prepared)
            else:
                gate_rejected_count += 1

        validation_errors = [
            {
                "index": error.index,
                "company_name": (
                    error.company_name
                ),
                "title": error.title,
                "source_name": (
                    error.source_name
                ),
                "reason": error.reason,
            }
            for error
            in validation_result.errors
        ]

        errors = [
            *extraction_errors,
            *validation_errors,
        ]

        report = {
            "extracted_at": (
                datetime.now(
                    timezone.utc
                ).isoformat(
                    timespec="seconds"
                )
            ),
            "provider": (
                self.provider.__class__.__name__
            ),
            "page_count": (
                len(data.pages)
            ),
            "raw_record_count": (
                len(all_raw_records)
            ),
            "valid_record_count": (
                len(
                    validation_result
                    .valid_records
                )
            ),
            "invalid_record_count": (
                len(
                    validation_result
                    .errors
                )
            ),
            "duplicate_count": (
                len(
                    deduplication_result
                    .duplicate_records
                )
            ),
            "prepared_count": (
                len(gated_records)
            ),
            "basic_gate_rejected_count": gate_rejected_count,
            "pending_count": (
                len(
                    pending_followups
                )
            ),
            "error_count": (
                len(errors)
            ),
            "errors": errors,
        }

        logger.info(
            "job_extraction extracted=%s prepared=%s validation_failures=%s duplicates=%s pending=%s",
            len(all_raw_records),
            len(gated_records),
            len(validation_result.errors),
            len(deduplication_result.duplicate_records),
            len(pending_followups),
        )
        for error in validation_errors:
            logger.warning(
                "job_extraction validation_failed title=%s reason=%s",
                error.get("title"),
                error.get("reason"),
            )
        for record in deduplication_result.unique_records:
            logger.info(
                "job_extraction graduation title=%s years=%s window=%s..%s requirement=%s",
                record.title,
                record.graduation_years,
                record.graduation_start,
                record.graduation_end,
                record.graduation_requirement,
            )

        return JobExtractionOutput(
            raw_records=all_raw_records,
            prepared_records=gated_records,
            duplicate_records=(
                deduplication_result
                .duplicate_records
            ),
            pending_followups=(
                pending_followups
            ),
            report=report,
        )
