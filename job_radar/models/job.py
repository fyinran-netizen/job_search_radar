"""Job data models used throughout the pipeline."""

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
    """A job record as collected from a source before cleaning."""

    model_config = ConfigDict(str_strip_whitespace=True)

    company_name: str | None = None
    company_type: str | None = None
    title: str | None = None
    location: str | None = None
    description: str | None = None
    requirements: str | None = None
    recruitment_type: str | None = None
    graduation_years: list[str] = Field(default_factory=list)
    published_at: str | None = None
    deadline: str | None = None
    apply_url: str | None = None
    source_url: str | None = None
    source_name: str | None = None
    is_official: bool = False

    @field_validator("graduation_years", mode="before")
    @classmethod
    def parse_graduation_years(cls, value: Any) -> list[str]:
        """Accept semicolon/comma separated years from CSV demo data."""

        if value is None or value == "":
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [item.strip() for item in str(value).replace(",", ";").split(";") if item.strip()]


class JobRecord(RawJobRecord):
    """A validated, normalized, matched, and persistable job record."""

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
