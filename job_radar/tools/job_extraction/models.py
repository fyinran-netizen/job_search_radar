"""Data models used by the job extraction capability."""

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Page inputs are owned by page analysis.  These imports remain as a narrow
# public re-export for serialized/older callers; extraction itself imports
# them from page_analysis.models.
from job_radar.tools.page_analysis.models import AIPageInput, ImportantLink


APPLICATION_STATUSES = [
    "未查看",
    "感兴趣",
    "准备投递",
    "已投递",
    "笔试",
    "一面",
    "二面",
    "Offer",
    "拒绝",
    "放弃",
    "已过期",
]


ApplicationStatus = Literal[
    "未查看",
    "感兴趣",
    "准备投递",
    "已投递",
    "笔试",
    "一面",
    "二面",
    "Offer",
    "拒绝",
    "放弃",
    "已过期",
]


def utc_now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class RawJobRecord(BaseModel):
    """Raw factual job fields extracted from a source page."""

    model_config = ConfigDict(str_strip_whitespace=True)

    company_name: str | None = None
    company_type: str | None = None

    title: str | None = None
    location: str | None = None

    description: str | None = None
    requirements: str | None = None

    recruitment_type: str | None = None

    graduation_years: list[str] = Field(default_factory=list)
    graduation_start: str | None = None
    graduation_end: str | None = None
    graduation_requirement: str | None = None

    start_date: str | None = None
    start_date_text: str | None = None

    published_at: str | None = None
    deadline: str | None = None

    apply_url: str | None = None

    source_url: str | None = None
    source_name: str | None = None
    is_official: bool = False

    @field_validator("graduation_years", mode="before")
    @classmethod
    def parse_graduation_years(cls, value: Any) -> list[str]:
        """Accept list or separated graduation-year values."""

        if value is None or value == "":
            return []

        if isinstance(value, list):
            return [
                str(item).strip()
                for item in value
                if str(item).strip()
            ]

        text = str(value).replace(",", ";")

        return [
            item.strip()
            for item in text.split(";")
            if item.strip()
        ]


class JobRecord(RawJobRecord):
    """Validated and normalized job record used downstream."""

    id: int | None = None

    normalized_company_name: str
    normalized_title: str
    normalized_location: str

    deduplication_key: str

    match_score: int = 0
    match_reasons: list[str] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)

    status: ApplicationStatus = "未查看"
    notes: str = ""

    first_seen_at: str = Field(default_factory=utc_now_iso)
    last_seen_at: str = Field(default_factory=utc_now_iso)
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class ExtractedPageContext(BaseModel):
    """Fields shared by jobs extracted from one page."""

    company_name: str | None = None
    recruitment_type: str | None = None

    graduation_years: list[str | int] = Field(
        default_factory=list
    )

    graduation_start: str | None = None
    graduation_end: str | None = None
    graduation_requirement: str | None = None

    start_date: str | None = None
    start_date_text: str | None = None

    published_at: str | None = None
    deadline: str | None = None


class ExtractedJobDetail(BaseModel):
    """Fields belonging to one concrete job."""

    title: str | None = None
    location: str | None = None

    description: str | None = None
    requirements: str | None = None


class PageJobExtraction(BaseModel):
    """AI extraction result for one input page."""

    page_id: str

    page_context: ExtractedPageContext

    jobs: list[ExtractedJobDetail] = Field(
        default_factory=list
    )
