"""Mock page acquisition tool for local agent testing."""

from typing import Any

from pydantic import BaseModel

from job_radar.tools.web_search.models import CandidateSource
from job_radar.tools.page_acquisition.models import PageDocument, PageFetchEvidence
from job_radar.tools.base import BaseTool


MOCK_PAGES = {
    "mock://future-bank/campus": """
---JOB---
company_name: Future Bank
company_type: Bank
title: Technology Graduate Analyst
location: Sydney
description: Graduate analyst program supporting digital banking platforms and analytics delivery.
requirements: Python; SQL; stakeholder communication; 2026 graduates
recruitment_type: Graduate Program
graduation_years: 2026;2027
published_at: 2026-07-20
deadline: 2026-09-30
apply_url: https://careers.example/future-bank/technology-graduate-analyst
source_url: mock://future-bank/campus
source_name: Future Bank Careers
is_official: true
---JOB---
company_name: Future Bank
company_type: Bank
title: Data Analyst Graduate Program
location: Shanghai
description: Campus program focused on reporting, data quality, and branch performance analytics.
requirements: SQL; Python; data analysis; 2026 graduates
recruitment_type: Campus Recruitment
graduation_years: 2026
published_at: 2026-07-21
deadline: 2026-10-15
apply_url: https://careers.example/future-bank/data-analyst-graduate
source_url: mock://future-bank/campus
source_name: Future Bank Careers
is_official: true
""",
    "mock://global-tech/graduates": """
---JOB---
company_name: Global Tech
company_type: Technology
title: Software Engineer Graduate
location: Remote
description: Graduate engineering role building internal developer tools and data services.
requirements: Python; testing; distributed systems; 2026 graduates
recruitment_type: Graduate Program
graduation_years: 2026
published_at: 2026-07-22
deadline: 2026-09-20
apply_url: https://careers.example/global-tech/software-engineer-graduate
source_url: mock://global-tech/graduates
source_name: Global Tech Careers
is_official: true
""",
}


class MockPageTool(BaseTool):
    """Return deterministic page text without network access."""

    name = "acquire_page"

    def run(self, payload: BaseModel | dict[str, Any]) -> PageDocument:
        """Collect mock page content for a selected candidate source."""

        source = payload if isinstance(payload, CandidateSource) else CandidateSource.model_validate(payload)
        text = MOCK_PAGES.get(source.url, "")
        return PageDocument(
            url=source.url,
            source_name=source.source_name,
            title=source.title,
            text=text,
            fetch_evidence=PageFetchEvidence(
                status_code=200,
                final_url=source.url,
                content_type="text/plain",
                fetch_method="unknown",
                attempts=1,
            ),
        )


