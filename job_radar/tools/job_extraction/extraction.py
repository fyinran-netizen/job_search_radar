"""AI-backed extraction of factual job records from prepared pages."""

import re
from urllib.parse import urlparse

from pydantic import TypeAdapter

from job_radar.infra.llm.base import AIProvider
from job_radar.infra.llm.prompt_builder import build_json_prompt
from job_radar.infra.llm.prompt_loader import load_runtime_prompt

from job_radar.tools.job_extraction.models import (
    AIPageInput,
    ImportantLink,
    PageJobExtraction,
    RawJobRecord,
)

from job_radar.tools.page_acquisition.models import PageDocument
from job_radar.tools.page_analysis.cleaning import clean_page_text, parse_acquired_page
from job_radar.tools.page_analysis.preparation import (
    build_ai_page_input,
    extract_important_links,
    prepare_page,
)


_VISIBLE_URL_PATTERN = re.compile(
    r"https?://[^\s<>\"']+"
)

_TRAILING_URL_PUNCTUATION = (
    ".,;:!?)]}，。；：！？）》】」』、"
)


def _legacy_build_ai_page_input(
    page: PageDocument,
    max_text_chars: int = 12000,
) -> AIPageInput:
    """
    Convert collected page content into the minimal structured input
    required by semantic classification and job extraction.

    Deterministic provenance is preserved outside AI output.
    """

    page = parse_acquired_page(page)
    final_url = page.metadata.get("final_url")

    return AIPageInput(
        url=page.url,
        final_url=(
            final_url
            if isinstance(final_url, str)
            else None
        ),
        source_name=page.source_name,
        source_company_name=_optional_metadata_string(
            page,
            "company_name",
        ),
        company_type=_optional_metadata_string(
            page,
            "company_type",
        ),
        source_location=_optional_metadata_string(
            page,
            "location",
        ),
        is_official=bool(
            page.metadata.get(
                "is_official",
                False,
            )
        ),
        title=page.title,
        visible_text=clean_page_text(
            page.html,
            page.text,
            url=page.url,
            max_text_chars=max_text_chars,
        ).text,
        important_links=extract_important_links(
            page
        ),
    )


def _legacy_extract_important_links(
    page: PageDocument,
    max_links: int = 10,
) -> list[ImportantLink]:
    """
    Preserve links that may be useful during job extraction.

    This includes:
    - application links
    - attached documents
    - explicitly labelled source links
    - application URLs written directly in visible text
    """

    links = page.metadata.get(
        "links",
        [],
    )

    if not isinstance(links, list):
        links = []

    important_links: list[ImportantLink] = []
    seen_urls: set[str] = set()

    for link in links:
        if not isinstance(link, dict):
            continue

        url = link.get("href")

        if (
            not isinstance(url, str)
            or not url
        ):
            continue

        if url in seen_urls:
            continue

        text = link.get("text")

        link_text = (
            text.strip()
            if isinstance(text, str)
            else ""
        )

        important_link = _classify_link(
            url,
            link_text,
        )

        if important_link is None:
            continue

        important_links.append(
            important_link
        )

        seen_urls.add(url)

    # Some recruitment pages expose the actual application URL
    # only as visible text rather than as an HTML link.
    for link in _extract_visible_text_links(
        page.text
    ):
        if link.url in seen_urls:
            continue

        important_links.append(link)
        seen_urls.add(link.url)

    priority = {
        "apply": 0,
        "attachment": 1,
        "source": 2,
        "other": 3,
    }

    return sorted(
        important_links,
        key=lambda item: priority[
            item.kind
        ],
    )[:max_links]


class AIJobExtractionClient:
    """
    Extract factual RawJobRecord objects using a structured AI provider.

    This layer answers:
    - Which jobs are present on the page?
    - What factual fields are explicitly stated?

    It does not decide whether requirements are hard/preferred,
    and it does not match the job against the user profile.
    """

    def __init__(
        self,
        provider: AIProvider,
        skill_name: str = "job-extraction",
        max_text_chars: int = 12000,
        timeout_seconds: int = 240,
    ) -> None:
        self.provider = provider
        self.skill_name = skill_name
        self.max_text_chars = max_text_chars
        self.timeout_seconds = timeout_seconds

    def extract_jobs_from_page(
        self,
        page: PageDocument,
    ) -> list[RawJobRecord]:
        """
        Build AI input from a collected page and extract jobs.
        """

        payload = prepare_page(page, max_text_chars=self.max_text_chars).page

        return self.extract_jobs_from_input(
            payload
        )

    def extract_jobs_from_input(
        self,
        payload: AIPageInput,
        retry_instruction: str | None = None,
    ) -> list[RawJobRecord]:
        """
        Extract one or more jobs from one processed page.
        """

        skill = load_runtime_prompt(
            self.skill_name
        )

        prompt = build_json_prompt(
            skill,
            {
                "page": _semantic_page_payload(
                    payload,
                    "page-1",
                ),
                "output": (
                    "Return one JSON object with the same page_id, "
                    "semantic page_context fields, graduation eligibility "
                    "fields, education level fields, and per-job title, locations, "
                    "description, and requirements. "
                    "This is a job_detail page: return only the one primary "
                    "job on the page; ignore related, similar, recommended, "
                    "sidebar, and navigation jobs. Extract company_name "
                    "from the title or main JD body when explicitly stated. "
                    "Do not invent information that is not supported by "
                    "the page."
                    + (
                        f" {retry_instruction}"
                        if retry_instruction
                        else ""
                    )
                ),
            },
        )

        data = self.provider.generate_json(
            prompt,
            timeout_seconds=self.timeout_seconds,
        )

        extraction = (
            PageJobExtraction.model_validate(
                data
            )
        )

        if extraction.page_id != "page-1":
            raise ValueError(
                "Unexpected extraction page_id: "
                f"{extraction.page_id}"
            )

        return _to_raw_records(
            extraction,
            payload,
        )

    def extract_jobs_from_inputs(
        self,
        payloads: list[AIPageInput],
        retry_instruction: str | None = None,
    ) -> list[RawJobRecord]:
        """
        Extract jobs from multiple processed pages in one AI call.
        """

        if not payloads:
            return []

        if len(payloads) == 1:
            return self.extract_jobs_from_input(
                payloads[0],
                retry_instruction=retry_instruction,
            )

        skill = load_runtime_prompt(
            self.skill_name
        )

        pages_by_id = {
            f"page-{index}": payload
            for index, payload in enumerate(
                payloads,
                start=1,
            )
        }

        prompt = build_json_prompt(
            skill,
            {
                "pages": [
                    _semantic_page_payload(
                        payload,
                        page_id,
                    )
                    for page_id, payload
                    in pages_by_id.items()
                ],
                "output": (
                    "Return a JSON array with one object per input page. "
                    "Each object must contain the unchanged page_id, "
                    "semantic page_context fields, graduation eligibility "
                    "fields, education level fields, and only the one primary job "
                    "for each input job_detail page. Ignore related, similar, "
                    "recommended, sidebar, and navigation jobs. Extract "
                    "company_name from the title or main JD body when "
                    "explicitly stated. "
                    "Do not invent information that is not supported by "
                    "the page."
                    + (
                        f" {retry_instruction}"
                        if retry_instruction
                        else ""
                    )
                ),
            },
        )

        data = self.provider.generate_json(
            prompt,
            timeout_seconds=self.timeout_seconds,
        )

        extractions = TypeAdapter(
            list[PageJobExtraction]
        ).validate_python(
            data
        )

        extracted_ids = [
            extraction.page_id
            for extraction in extractions
        ]

        if len(extracted_ids) != len(
            set(extracted_ids)
        ):
            raise ValueError(
                "AI extraction returned duplicate page_id values."
            )

        if set(extracted_ids) != set(
            pages_by_id
        ):
            raise ValueError(
                "AI extraction page_id values do not match "
                "the input pages."
            )

        records: list[RawJobRecord] = []

        for extraction in extractions:
            page_input = pages_by_id[
                extraction.page_id
            ]

            records.extend(
                _to_raw_records(
                    extraction,
                    page_input,
                )
            )

        return records


def _to_raw_records(
    extraction: PageJobExtraction,
    page_input: AIPageInput,
) -> list[RawJobRecord]:
    """
    Merge AI-extracted semantic fields with deterministic provenance.

    source_url/source_name/is_official are supplied by the program,
    rather than trusted to the AI.
    """

    context = (
        extraction.page_context.model_dump()
    )

    context["company_name"] = (
        context.get("company_name")
        or _extract_explicit_company_name(page_input)
        or page_input.source_company_name
    )

    context.update(
        {
            "company_type": (
                page_input.company_type
            ),
            "apply_url": (
                _first_apply_url(
                    page_input.important_links
                )
            ),
            "source_url": (
                page_input.url
            ),
            "source_name": (
                page_input.source_name
                or _source_name_from_url(
                    page_input
                )
            ),
            "is_official": (
                page_input.is_official
            ),
        }
    )

    records: list[RawJobRecord] = []

    for job in extraction.jobs:
        data = {
            **context,
            **job.model_dump(),
        }

        if not data.get("locations") and page_input.source_location:
            data["locations"] = [page_input.source_location]

        records.append(
            RawJobRecord.model_validate(
                data
            )
        )

    return records


def _semantic_page_payload(
    page_input: AIPageInput,
    page_id: str,
) -> dict[str, str]:
    """
    Send only fields requiring semantic interpretation to the AI.
    """

    return {
        "page_id": page_id,
        "title": page_input.title,
        "visible_text": (
            page_input.visible_text
        ),
    }


_COMPANY_LABEL_PATTERN = re.compile(
    r"^(?:company|employer|hiring company|organization|公司名称|招聘单位|用人单位|雇主)\s*[:：]\s*(.+?)\s*$",
    re.IGNORECASE,
)
_ABOUT_COMPANY_PATTERN = re.compile(
    r"^(?:about|关于)\s+(.+?)\s*$",
    re.IGNORECASE,
)
_UNDISCLOSED_COMPANY_MARKERS = (
    "our client",
    "the client",
    "我们的客户",
    "客户公司",
    "匿名雇主",
)
_COMPANY_SUFFIX_PATTERN = re.compile(
    r"(?:\b(?:inc|corp|corporation|co\.?|ltd|limited|llc|plc)\.?$|有限公司$|集团$|科技$|银行$)",
    re.IGNORECASE,
)


def _extract_explicit_company_name(page_input: AIPageInput) -> str | None:
    """Extract only conservatively labelled employer names from page text."""

    for line_index, raw_line in enumerate(
        (page_input.title, *page_input.visible_text.splitlines())
    ):
        line = raw_line.strip().strip("|-—–")
        if not line:
            continue
        for pattern in (_COMPANY_LABEL_PATTERN, _ABOUT_COMPANY_PATTERN):
            match = pattern.match(line)
            if not match:
                continue
            candidate = match.group(1).strip(" .,:;，。：")
            if candidate and not any(
                marker in candidate.casefold()
                for marker in _UNDISCLOSED_COMPANY_MARKERS
            ):
                return candidate
        if line_index == 0:
            for candidate in re.split(r"\s*[|｜—–]\s*|\s+-\s+", line):
                candidate = candidate.strip(" .,:;，。：")
                if (
                    candidate
                    and _COMPANY_SUFFIX_PATTERN.search(candidate)
                    and not any(
                        marker in candidate.casefold()
                        for marker in _UNDISCLOSED_COMPANY_MARKERS
                    )
                ):
                    return candidate
    return None


def _classify_link(
    url: str,
    text: str,
) -> ImportantLink | None:
    """
    Classify links using deterministic signals.
    """

    text_lower = text.lower()

    path = urlparse(
        url
    ).path.lower()

    if path.endswith(
        (
            ".pdf",
            ".doc",
            ".docx",
            ".xls",
            ".xlsx",
        )
    ):
        return ImportantLink(
            url=url,
            text=text,
            kind="attachment",
            reason="document_file",
        )

    if _contains_any(
        text_lower,
        [
            "apply",
            "application",
            "submit",
            "resume",
            "投递",
            "申请",
            "报名",
            "简历",
            "网申",
            "应聘",
        ],
    ):
        return ImportantLink(
            url=url,
            text=text,
            kind="apply",
            reason="apply_signal",
        )

    if _contains_any(
        text_lower,
        [
            "source",
            "original source",
            "来源",
        ],
    ):
        return ImportantLink(
            url=url,
            text=text,
            kind="source",
            reason="source_signal",
        )

    return None


def _extract_visible_text_links(
    text: str,
) -> list[ImportantLink]:
    """
    Find explicit recruitment/application URLs written in visible text.
    """

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    links: list[ImportantLink] = []

    for index, line in enumerate(
        lines
    ):
        context_start = max(
            0,
            index - 1,
        )

        context_end = min(
            len(lines),
            index + 2,
        )

        context = " ".join(
            lines[
                context_start:
                context_end
            ]
        ).lower()

        if not _contains_any(
            context,
            [
                "apply",
                "application",
                "报名",
                "投递",
                "网申",
                "招聘网站",
                "校招官网",
            ],
        ):
            continue

        for match in (
            _VISIBLE_URL_PATTERN.finditer(
                line
            )
        ):
            url = (
                match.group(0)
                .rstrip(
                    _TRAILING_URL_PUNCTUATION
                )
            )

            if urlparse(
                url
            ).path.lower().endswith(
                (
                    ".pdf",
                    ".doc",
                    ".docx",
                    ".xls",
                    ".xlsx",
                )
            ):
                continue

            links.append(
                ImportantLink(
                    url=url,
                    text=line,
                    kind="apply",
                    reason=(
                        "visible_text_apply_url"
                    ),
                )
            )

    return links


def _first_apply_url(
    links: list[ImportantLink],
) -> str | None:
    """
    Return the first explicitly identified application link.
    """

    for link in links:
        if link.kind == "apply":
            return link.url

    return None


def _source_name_from_url(
    page_input: AIPageInput,
) -> str:
    """
    Derive a fallback source name from the page URL.
    """

    parsed = urlparse(
        page_input.final_url
        or page_input.url
    )

    return (
        parsed.netloc
        or page_input.title
        or page_input.url
    )


def _optional_metadata_string(
    page: PageDocument,
    key: str,
) -> str | None:
    """
    Read an optional non-empty string from page metadata.
    """

    value = page.metadata.get(
        key
    )

    if (
        isinstance(value, str)
        and value.strip()
    ):
        return value

    return None


def _contains_any(
    text: str,
    markers: list[str],
) -> bool:
    """
    Return whether any marker appears in text.
    """

    return any(
        marker in text
        for marker in markers
    )
